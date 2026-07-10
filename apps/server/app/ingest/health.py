"""Phone health payloads (Shortcuts/Health Auto Export) -> health_samples,
workouts -- docs/API.md #2c, docs/DATA_MODEL.md #2, docs/phases/PHASE-2-ingestion.md.

Accepts BOTH payload shapes, sniffed by shape (API.md #2):

Path A (default, free) -- Sukumo's own canonical shape, POSTed by an iOS
Shortcut::

    {"metrics": [{"metric": "step_count", "date": "2026-07-10", "qty": 8123,
                  "unit": "count"}],
     "workouts": [{"name": "Traditional Strength Training", "start": "...",
                   "end": "...", "duration_s": 3120, "kcal": 310,
                   "distance_m": 0}]}

Path B (fallback, paid) -- Health Auto Export's REST automation, metrics and
workouts wrapped in a ``"data"`` envelope::

    {"data": {"metrics": [{"name": "step_count", "units": "count",
                            "data": [{"date": "2026-07-10 00:00:00 +0000",
                                      "qty": 8123}]}],
              "workouts": [{"id": "...", "name": "Running", "start": "...",
                            "end": "...", "duration": 1800,
                            "activeEnergyBurned": {"qty": 210, "units": "kcal"},
                            "distance": {"qty": 3.1, "units": "km"}}]}}

ONE mapping dict (``METRIC_ALIASES``) covers both shapes' metric-name
spellings; anything not in it is stored verbatim under its own (slugified)
name rather than rejected -- DATA_MODEL #2's rule. ``sleep_analysis``-style
entries (HAE's aggregated asleep/inBed fields) fan out into two rows:
``sleep_asleep`` + ``sleep_inbed``.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from dateutil import parser as dateutil_parser
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import HealthSample, Workout

# ---------------------------------------------------------------- metrics --
# raw incoming name (slugified: lowercased, non-alnum runs -> '_') ->
# canonical snake_case metric name. Sukumo's own Shortcut already sends
# canonical names; these aliases are the Health Auto Export / HealthKit
# spellings that differ. Deliberately ONE dict for both paths (API.md #2c).
METRIC_ALIASES: dict[str, str] = {
    "step_count": "step_count",
    "steps": "step_count",
    "stepcount": "step_count",
    "active_energy": "active_energy",
    "active_calories": "active_energy",
    "activeenergyburned": "active_energy",
    "resting_heart_rate": "resting_heart_rate",
    "restingheartrate": "resting_heart_rate",
    "heart_rate": "heart_rate",
    "heartrate": "heart_rate",
    "stand_hours": "stand_hours",
    "stand_time": "stand_hours",
    "standhours": "stand_hours",
    "apple_stand_hour": "stand_hours",
    "walking_running_distance": "walking_running_distance",
    "distance_walking_running": "walking_running_distance",
    "walking_and_running_distance": "walking_running_distance",
    "exercise_minutes": "exercise_minutes",
    "apple_exercise_time": "exercise_minutes",
    "flights_climbed": "flights_climbed",
    "flightsclimbed": "flights_climbed",
}
SLEEP_METRIC_SLUGS = {"sleep_analysis", "sleepanalysis", "sleep"}
KNOWN_CANONICAL_METRICS = set(METRIC_ALIASES.values()) | {"sleep_asleep", "sleep_inbed"}

# raw workout name (slugified) -> wtype slug. Habits whose evidence is
# 'workouts:wtype in cfg' (e.g. the gym habit) match against these slugs via
# their config_json (app.habits.derive_auto_habit_events). Anything not
# listed here still ingests fine -- its slug just becomes the wtype verbatim.
WORKOUT_TYPE_ALIASES: dict[str, str] = {
    "traditional_strength_training": "strength",
    "functional_strength_training": "strength",
    "core_training": "strength",
    "high_intensity_interval_training": "hiit",
    "hiit": "hiit",
    "running": "run",
    "outdoor_run": "run",
    "indoor_run": "run",
    "walking": "walk",
    "outdoor_walk": "walk",
    "indoor_walk": "walk",
    "cycling": "cycle",
    "outdoor_cycle": "cycle",
    "indoor_cycle": "cycle",
    "yoga": "yoga",
    "swimming": "swim",
    "elliptical": "cardio",
    "rowing": "row",
}


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _normalize_dt(raw: str) -> str:
    """Any incoming date/datetime string -> naive UTC 'YYYY-MM-DD HH:MM:SS'
    (the siblings' storage convention). Bare dates (daily aggregates) become
    midnight that day."""
    raw = raw.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return f"{raw} 00:00:00"
    dt = dateutil_parser.parse(raw)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _extract_shape(payload: dict) -> tuple[list[dict], list[dict], str]:
    """Sniff Path A (flat) vs Path B (HAE's 'data' envelope, API.md #2b)."""
    if isinstance(payload.get("data"), dict):
        data = payload["data"]
        return list(data.get("metrics") or []), list(data.get("workouts") or []), "hae"
    return list(payload.get("metrics") or []), list(payload.get("workouts") or []), "shortcut"


def _expand_sleep(point: dict, unit: str | None) -> list[tuple[str, float, str | None]]:
    """HAE's Sleep Analysis entries carry asleep/inBed (or totalSleep)
    sub-fields per date; Path A, lacking that aggregation, may just send a
    flat qty -- treated as sleep_asleep only."""
    rows: list[tuple[str, float, str | None]] = []
    asleep = point.get("asleep", point.get("totalSleep"))
    in_bed = point.get("inBed")
    if asleep is not None or in_bed is not None:
        if asleep is not None:
            rows.append(("sleep_asleep", float(asleep), unit or "min"))
        if in_bed is not None:
            rows.append(("sleep_inbed", float(in_bed), unit or "min"))
        return rows
    qty = point.get("qty")
    if qty is not None:
        rows.append(("sleep_asleep", float(qty), unit))
    return rows


def _rows_for_metric_entry(entry: dict) -> list[tuple[str, str, float, str | None]]:
    """One incoming metric entry -- Path A's flat {metric,date,qty,unit} or
    Path B's nested {name,units,data:[{date,qty|avg}]} -- -> a list of
    (canonical_metric, ts_start, value, unit) rows."""
    raw_name = entry.get("metric") or entry.get("name") or ""
    slug = _slugify(raw_name)
    is_sleep = slug in SLEEP_METRIC_SLUGS

    if isinstance(entry.get("data"), list):
        unit = entry.get("units") or entry.get("unit")
        points = entry["data"]
    else:
        unit = entry.get("unit") or entry.get("units")
        points = [entry]

    rows: list[tuple[str, str, float, str | None]] = []
    for point in points:
        date_raw = point.get("date")
        if not date_raw:
            continue
        ts_start = _normalize_dt(str(date_raw))
        if is_sleep:
            for metric_name, value, point_unit in _expand_sleep(point, unit):
                rows.append((metric_name, ts_start, value, point_unit))
            continue
        value = point.get("qty")
        if value is None:
            value = point.get("avg")  # HAE's aggregated avg/min/max metrics (e.g. heart_rate)
        if value is None:
            continue
        canonical = METRIC_ALIASES.get(slug, slug)  # unknown metrics: stored verbatim, never dropped
        rows.append((canonical, ts_start, float(value), unit))
    return rows


def _upsert_sample(
    session: Session, user_id: int, metric: str, ts_start: str, value: float, unit: str | None, source: str
) -> int:
    existing = session.scalar(
        select(HealthSample).where(
            HealthSample.user_id == user_id,
            HealthSample.metric == metric,
            HealthSample.ts_start == ts_start,
            HealthSample.source == source,
        )
    )
    if existing is not None:
        changed = existing.value != value or existing.unit != unit
        existing.value = value
        existing.unit = unit
        return 1 if changed else 0
    session.add(
        HealthSample(
            user_id=user_id, metric=metric, ts_start=ts_start, ts_end=None, value=value, unit=unit, source=source
        )
    )
    return 1


def _wtype_for(raw_name: str) -> str:
    slug = _slugify(raw_name)
    return WORKOUT_TYPE_ALIASES.get(slug, slug)


def _workout_duration_s(w: dict) -> int | None:
    if w.get("duration_s") is not None:
        return int(round(float(w["duration_s"])))
    if w.get("duration") is not None:  # HAE workouts v2: seconds
        return int(round(float(w["duration"])))
    return None


def _workout_kcal(w: dict) -> float | None:
    if w.get("kcal") is not None:
        return float(w["kcal"])
    energy = w.get("activeEnergyBurned")
    if isinstance(energy, dict) and energy.get("qty") is not None:
        qty = float(energy["qty"])
        units = (energy.get("units") or "kcal").lower()
        if units in ("kj", "kilojoule", "kilojoules"):
            return qty / 4.184
        return qty
    return None


def _workout_distance_m(w: dict) -> float | None:
    if w.get("distance_m") is not None:
        return float(w["distance_m"])
    dist = w.get("distance")
    if isinstance(dist, dict) and dist.get("qty") is not None:
        qty = float(dist["qty"])
        units = (dist.get("units") or "m").lower()
        if units in ("km", "kilometer", "kilometers", "kilometre", "kilometres"):
            return qty * 1000
        if units in ("mi", "mile", "miles"):
            return qty * 1609.34
        return qty
    return None


def _upsert_workout(session: Session, user_id: int, w: dict) -> int:
    raw_name = w.get("name") or "unknown"
    wtype = _wtype_for(raw_name)
    start_raw = w.get("start") or w.get("startDate")
    if not start_raw:
        raise ValueError("workout missing 'start'")
    ts_start = _normalize_dt(str(start_raw))
    end_raw = w.get("end") or w.get("endDate")
    ts_end = _normalize_dt(str(end_raw)) if end_raw else None
    duration_s = _workout_duration_s(w)
    kcal = _workout_kcal(w)
    distance_m = _workout_distance_m(w)
    # HAE gives a real id; Path A's Shortcut can't, so derive one from
    # (wtype, ts_start) -- deterministic, so re-posts stay idempotent.
    provider_uid = str(w["id"]) if w.get("id") else f"derived:{wtype}:{ts_start}"

    existing = session.scalar(
        select(Workout).where(
            Workout.user_id == user_id, Workout.provider_uid == provider_uid, Workout.source == raw_name
        )
    )
    if existing is not None:
        changed = (
            existing.wtype,
            existing.ts_start,
            existing.ts_end,
            existing.duration_s,
            existing.kcal,
            existing.distance_m,
        ) != (wtype, ts_start, ts_end, duration_s, kcal, distance_m)
        existing.wtype = wtype
        existing.ts_start = ts_start
        existing.ts_end = ts_end
        existing.duration_s = duration_s
        existing.kcal = kcal
        existing.distance_m = distance_m
        return 1 if changed else 0

    session.add(
        Workout(
            user_id=user_id,
            wtype=wtype,
            ts_start=ts_start,
            ts_end=ts_end,
            duration_s=duration_s,
            kcal=kcal,
            distance_m=distance_m,
            source=raw_name,  # API.md #2c: "the raw name kept in source"
            provider_uid=provider_uid,
        )
    )
    return 1


def ingest_health_payload(session: Session, user_id: int, payload: dict) -> dict:
    """API.md #2c: ``{"accepted": n, "upserted": n, "unknown_metrics": [...]}``.
    ``accepted`` counts every data point processed (metrics + workouts);
    ``upserted`` counts rows actually written or changed -- a byte-identical
    re-POST therefore reports ``upserted: 0`` (DATA_MODEL's idempotency law).
    """
    metrics_in, workouts_in, source_label = _extract_shape(payload)

    accepted = 0
    upserted = 0
    unknown_metrics: set[str] = set()

    for entry in metrics_in:
        for metric, ts_start, value, unit in _rows_for_metric_entry(entry):
            accepted += 1
            if metric not in KNOWN_CANONICAL_METRICS:
                unknown_metrics.add(metric)
            upserted += _upsert_sample(session, user_id, metric, ts_start, value, unit, source_label)

    for w in workouts_in:
        accepted += 1
        upserted += _upsert_workout(session, user_id, w)

    session.commit()
    return {"accepted": accepted, "upserted": upserted, "unknown_metrics": sorted(unknown_metrics)}
