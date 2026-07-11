"""Daily movement aggregate from raw ``location_points`` -- docs/MEMORY.md
#2-3, docs/DATA_MODEL.md #2/#8, docs/API.md #3b.

Per Europe/London day this produces the ``stats_json`` movement block::

    {"trace": [[lat, lon], ...],   # Douglas-Peucker-simplified, <= 200 points
     "distance_m": 6212,           # haversine over the time-ordered points
     "away_min": 187}              # minutes outside 150 m of home (null when
                                   #   SUKUMO_HOME_LAT/LON are unset)

Choices, documented per the plan:

- **Absolute coordinates** are stored in the trace (rounded to 5 dp, ~1 m),
  not normalised offsets -- stats_json already lives in the primary-only
  journal (never the dashboard, partner portal, or any push -- MEMORY #2),
  and absolute coords keep the day re-renderable without a second lookup.
- **Noise gate**: a jump > 200 m between consecutive points < 30 s apart is
  GPS scatter, not travel -- excluded from the distance sum.
- **Away minutes** accumulate the time between consecutive points that are
  BOTH outside the 150 m home radius; a gap > 60 min between points is a
  data hole (phone off, no fix), not evidence of being out, so it never
  counts.
- **Determinism** (the journal's law, PHASE-7): points are ordered by
  (ts, lat, lon), coordinates rounded before simplification, and the
  Douglas-Peucker epsilon ladder is fixed -- same points in, same block out.
- **Retention** (DATA_MODEL #8): ``prune_location_points`` -- called by the
  nightly assembly (``assemble_yesterday``) -- deletes raw points older than
  90 days, but only for days whose ``journal_days`` aggregate already exists.

Pure stdlib maths -- no new dependencies (Douglas-Peucker is ~30 lines).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import JournalDay, LocationPoint

LONDON = ZoneInfo("Europe/London")

EARTH_RADIUS_M = 6_371_000.0
HOME_RADIUS_M = 150.0
NOISE_JUMP_M = 200.0
NOISE_WINDOW_S = 30.0
AWAY_MAX_GAP_S = 3600.0
MAX_TRACE_POINTS = 200
BASE_EPSILON_M = 10.0
RETAIN_DAYS = 90


# ------------------------------------------------------------------ geometry --
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _project_m(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Equirectangular projection to local metres around the track's mid
    latitude -- good to well under DP epsilon at day-trip scale, and cheap."""
    mid_lat = (min(p[0] for p in points) + max(p[0] for p in points)) / 2
    kx = math.cos(math.radians(mid_lat)) * math.pi / 180 * EARTH_RADIUS_M
    ky = math.pi / 180 * EARTH_RADIUS_M
    return [(p[1] * kx, p[0] * ky) for p in points]


def _perp_dist(pt: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance from ``pt`` to segment ``a-b`` in the projected plane."""
    ax, ay = a
    bx, by = b
    px, py = pt
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def douglas_peucker(points: list[tuple[float, float]], epsilon_m: float) -> list[tuple[float, float]]:
    """Classic DP line simplification over (lat, lon) points, tolerance in
    metres. Iterative (explicit stack) so a long day can't hit the recursion
    limit. Endpoints always survive."""
    n = len(points)
    if n <= 2:
        return list(points)
    proj = _project_m(points)
    keep = [False] * n
    keep[0] = keep[n - 1] = True
    stack: list[tuple[int, int]] = [(0, n - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi - lo < 2:
            continue
        best_d = -1.0
        best_i = lo
        for i in range(lo + 1, hi):
            d = _perp_dist(proj[i], proj[lo], proj[hi])
            if d > best_d:
                best_d = d
                best_i = i
        if best_d > epsilon_m:
            keep[best_i] = True
            stack.append((lo, best_i))
            stack.append((best_i, hi))
    return [p for p, k in zip(points, keep) if k]


def simplify_trace(
    points: list[tuple[float, float]], max_points: int = MAX_TRACE_POINTS
) -> list[tuple[float, float]]:
    """DP at a fixed 10 m base tolerance, doubling epsilon until the trace
    fits in ``max_points``. The ladder is fixed, so the result is a pure
    function of the input (the determinism law)."""
    simplified = douglas_peucker(points, BASE_EPSILON_M)
    epsilon = BASE_EPSILON_M
    while len(simplified) > max_points:
        epsilon *= 2
        simplified = douglas_peucker(points, epsilon)
    return simplified


# ----------------------------------------------------------------- gathering --
def _local_date_of(ts_utc: str) -> str:
    dt = datetime.strptime(ts_utc[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return dt.astimezone(LONDON).date().isoformat()


def _utc_window(local_date: str) -> tuple[str, str]:
    d = date.fromisoformat(local_date)
    start = (d - timedelta(days=1)).isoformat()
    end = (d + timedelta(days=1)).isoformat()
    return f"{start} 00:00:00", f"{end} 23:59:59"


def _seconds(ts_utc: str) -> float:
    dt = datetime.strptime(ts_utc[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _points_for(session: Session, local_date: str) -> list[LocationPoint]:
    lo, hi = _utc_window(local_date)
    rows = session.scalars(
        select(LocationPoint).where(LocationPoint.ts >= lo, LocationPoint.ts <= hi)
    ).all()
    same_day = [p for p in rows if _local_date_of(p.ts) == local_date]
    # Deterministic order independent of insertion order / autoincrement id.
    same_day.sort(key=lambda p: (p.ts, p.lat, p.lon))
    return same_day


# ----------------------------------------------------------------- aggregate --
def day_movement(
    session: Session, local_date: str, *, home: tuple[float, float] | None
) -> dict | None:
    """The day's movement block for ``stats_json``, or None when the day has
    fewer than two usable points (no trace -> no block, MEMORY #3)."""
    points = _points_for(session, local_date)
    if len(points) < 2:
        return None

    distance = 0.0
    away_s = 0.0
    for a, b in zip(points, points[1:]):
        d = haversine_m(a.lat, a.lon, b.lat, b.lon)
        dt = _seconds(b.ts) - _seconds(a.ts)
        # GPS noise gate: a >200 m teleport inside 30 s is scatter, not travel.
        if not (d > NOISE_JUMP_M and dt < NOISE_WINDOW_S):
            distance += d
        if home is not None and 0 < dt <= AWAY_MAX_GAP_S:
            a_away = haversine_m(a.lat, a.lon, home[0], home[1]) > HOME_RADIUS_M
            b_away = haversine_m(b.lat, b.lon, home[0], home[1]) > HOME_RADIUS_M
            if a_away and b_away:
                away_s += dt

    rounded = [(round(p.lat, 5), round(p.lon, 5)) for p in points]
    deduped = [rounded[0]]
    for pt in rounded[1:]:
        if pt != deduped[-1]:
            deduped.append(pt)
    trace = simplify_trace(deduped)

    return {
        "trace": [[lat, lon] for lat, lon in trace],
        "distance_m": int(round(distance)),
        "away_min": int(round(away_s / 60)) if home is not None else None,
    }


# ----------------------------------------------------------------- retention --
def prune_location_points(session: Session, *, now: datetime | None = None) -> int:
    """DATA_MODEL #8: raw points live 90 days, then only the day's aggregate
    remains. Deletes points whose local day is older than the window AND
    already has a ``journal_days`` row -- a day assembly somehow missed keeps
    its raw points until it is assembled. Returns rows deleted."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now.astimezone(LONDON).date() - timedelta(days=RETAIN_DAYS)).isoformat()
    old = session.scalars(
        select(LocationPoint).where(LocationPoint.ts < f"{cutoff} 00:00:00")
    ).all()
    by_day: dict[str, list[LocationPoint]] = {}
    for p in old:
        d = _local_date_of(p.ts)
        if d < cutoff:
            by_day.setdefault(d, []).append(p)
    deleted = 0
    for d, pts in by_day.items():
        if session.get(JournalDay, d) is None:
            continue  # aggregate not written yet -- keep the raw points
        for p in pts:
            session.delete(p)
            deleted += 1
    session.commit()
    return deleted
