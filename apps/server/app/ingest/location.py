"""Overland GPS batches -> location_points -- docs/API.md #3b,
docs/DATA_MODEL.md #2.

Overland (https://overland.p3k.app, the free background GPS logger) POSTs
GeoJSON batches::

    {"locations": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [lon, lat]},
         "properties": {"timestamp": "2026-07-10T09:15:03Z",
                        "horizontal_accuracy": 10, "speed": 1.2,
                        "motion": ["walking"], "battery_level": 0.8, ...}},
        ...]}

and REQUIRES the literal response body ``{"result": "ok"}`` -- anything else
makes the app keep the batch and retry at the next interval, so the router
always returns that shape on 200 and the per-feature outcome lives in the
``sync_runs`` row instead.

Filtering (API.md #3b): a feature with ``horizontal_accuracy`` > 100 m (or a
negative accuracy -- an invalid fix) is DROPPED, as is anything malformed
(no Point geometry, unparseable timestamp, out-of-range coordinates). A
poison point must never wedge Overland's retry queue, so bad features are
counted, not raised. Only stripped-down rows are stored: ts/lat/lon/
accuracy/speed. ``motion``, ``battery_level`` and the rest of the payload
are deliberately discarded -- the movement aggregate (app/memory/movement.py)
needs nothing else, and the raw table stays as small as its 90-day life.

Idempotent on ``UNIQUE(user_id, ts, source)``: Overland re-sends whole
batches on any non-ok response, so re-delivery upserts (DATA_MODEL's
idempotency law). Timestamps are normalised to the household's naive-UTC
second granularity; two points inside the same second collapse to the first.
"""
from __future__ import annotations

from datetime import timezone

from dateutil import parser as dateutil_parser
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LocationPoint

MAX_ACCURACY_M = 100.0
SOURCE = "overland"


def _parse_feature(feat: object) -> dict | None:
    """One GeoJSON Feature -> a location_points row dict, or None to drop."""
    if not isinstance(feat, dict):
        return None
    geometry = feat.get("geometry")
    props = feat.get("properties")
    if not isinstance(geometry, dict) or not isinstance(props, dict):
        return None
    if geometry.get("type") != "Point":
        return None
    coords = geometry.get("coordinates")
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None
    try:
        lon = float(coords[0])
        lat = float(coords[1])
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None

    raw_ts = props.get("timestamp")
    if not raw_ts:
        return None
    try:
        dt = dateutil_parser.parse(str(raw_ts))
    except (ValueError, OverflowError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    ts = dt.strftime("%Y-%m-%d %H:%M:%S")

    accuracy = props.get("horizontal_accuracy")
    try:
        accuracy = float(accuracy) if accuracy is not None else None
    except (TypeError, ValueError):
        accuracy = None
    # The accuracy gate: > 100 m is GPS mush, < 0 is CoreLocation's "invalid
    # fix" sentinel -- both dropped (API.md #3b).
    if accuracy is not None and (accuracy < 0 or accuracy > MAX_ACCURACY_M):
        return None

    speed = props.get("speed")
    try:
        speed = float(speed) if speed is not None else None
    except (TypeError, ValueError):
        speed = None
    if speed is not None and speed < 0:  # -1 is CoreLocation's "unknown"
        speed = None

    return {"ts": ts, "lat": lat, "lon": lon, "accuracy_m": accuracy, "speed_ms": speed}


def ingest_location_payload(session: Session, user_id: int, payload: dict) -> dict:
    """Parse + upsert one Overland batch. Returns ``{"accepted": n,
    "dropped": n}`` for the sync_runs row (the HTTP response is always
    ``{"result": "ok"}`` -- the router owns that contract)."""
    locations = payload.get("locations")
    if not isinstance(locations, list):
        raise ValueError("payload has no 'locations' list")

    parsed: dict[str, dict] = {}  # ts -> row (first wins inside a batch)
    dropped = 0
    for feat in locations:
        row = _parse_feature(feat)
        if row is None:
            dropped += 1
            continue
        if row["ts"] in parsed:
            dropped += 1  # same-second duplicate inside the batch
            continue
        parsed[row["ts"]] = row

    accepted = 0
    if parsed:
        existing = set(
            session.scalars(
                select(LocationPoint.ts).where(
                    LocationPoint.user_id == user_id,
                    LocationPoint.source == SOURCE,
                    LocationPoint.ts.in_(list(parsed)),
                )
            ).all()
        )
        for ts, row in parsed.items():
            if ts in existing:
                continue  # idempotent re-delivery
            session.add(LocationPoint(user_id=user_id, source=SOURCE, **row))
            accepted += 1
    session.commit()
    return {"accepted": accepted, "dropped": dropped}
