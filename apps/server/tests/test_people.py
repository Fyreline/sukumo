"""People / occasions / gift vault + the calendar birthday import --
docs/DATA_MODEL.md §3, docs/phases/PHASE-4-dashboard.md build item 2.

Everything here is primary-only (403 for role='partner') — occasion/people
data never reaches the partner role in v1 through ANY endpoint. All fixture
names are synthetic (ARCHITECTURE §5.5).
"""
from __future__ import annotations

from tests.conftest import auth_headers, make_user


def _primary():
    return make_user(email="mack@example.com", display_name="Mack", role="primary")


def _partner():
    return make_user(email="amy@example.com", display_name="Amy", role="partner")


# ------------------------------------------------------------ auth guards --
def test_people_routes_require_jwt(client):
    for path in ("/api/people", "/api/occasions", "/api/gifts", "/api/people/candidates"):
        assert client.get(path).status_code == 401


def test_people_routes_are_primary_only(client):
    """The partner role gets a hard 403 from every people/occasion/gift
    route — the surprise-guard flag protects primary-vs-primary privacy,
    the role check protects the whole corner from the partner portal."""
    partner_id = _partner()
    headers = auth_headers(partner_id)
    for path in ("/api/people", "/api/occasions", "/api/gifts", "/api/people/candidates"):
        res = client.get(path, headers=headers)
        assert res.status_code == 403, path
    assert client.post("/api/people", json={"name": "X"}, headers=headers).status_code == 403
    assert (
        client.post(
            "/api/people/candidates/confirm", json={"name": "X", "month_day": "01-01"}, headers=headers
        ).status_code
        == 403
    )


# ----------------------------------------------------------------- people --
def test_create_person_with_birthday_materialises_yearly_occasion(client):
    user_id = _primary()
    headers = auth_headers(user_id)
    res = client.post(
        "/api/people",
        json={"name": "Taro Fixture", "relation": "friend", "birthday": "1990-09-22"},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["birthday"] == "1990-09-22"
    assert len(body["occasions"]) == 1
    occ = body["occasions"][0]
    assert occ["kind"] == "birthday"
    assert occ["recurrence"] == "yearly"
    assert occ["month_day"] == "09-22"
    assert occ["title"] == "Taro Fixture's birthday"


def test_patch_person_birthday_updates_the_auto_occasion_in_place(client):
    user_id = _primary()
    headers = auth_headers(user_id)
    person = client.post("/api/people", json={"name": "Hana Fixture", "birthday": "1991-03-05"}, headers=headers).json()

    patched = client.patch(f"/api/people/{person['id']}", json={"birthday": "1991-04-06"}, headers=headers).json()
    assert len(patched["occasions"]) == 1  # updated, not duplicated
    assert patched["occasions"][0]["month_day"] == "04-06"

    cleared = client.patch(f"/api/people/{person['id']}", json={"birthday": None}, headers=headers).json()
    assert cleared["birthday"] is None
    assert cleared["occasions"] == []  # auto occasion removed with it


def test_create_person_rejects_bad_birthday_and_duplicate_name(client):
    user_id = _primary()
    headers = auth_headers(user_id)
    assert client.post("/api/people", json={"name": "Bad Date", "birthday": "22-09"}, headers=headers).status_code == 422
    assert client.post("/api/people", json={"name": "Dup Fixture"}, headers=headers).status_code == 200
    assert client.post("/api/people", json={"name": "Dup Fixture"}, headers=headers).status_code == 409


def test_archive_person_hides_them_from_default_list(client):
    user_id = _primary()
    headers = auth_headers(user_id)
    person = client.post("/api/people", json={"name": "Old Friend"}, headers=headers).json()
    client.patch(f"/api/people/{person['id']}", json={"archived": True}, headers=headers)
    names = [p["name"] for p in client.get("/api/people", headers=headers).json()]
    assert "Old Friend" not in names
    names_all = [p["name"] for p in client.get("/api/people?include_archived=true", headers=headers).json()]
    assert "Old Friend" in names_all


# -------------------------------------------------------------- occasions --
def test_occasion_requires_exactly_one_of_month_day_or_date(client):
    user_id = _primary()
    headers = auth_headers(user_id)
    assert client.post("/api/occasions", json={"title": "Neither"}, headers=headers).status_code == 422
    assert (
        client.post(
            "/api/occasions", json={"title": "Both", "month_day": "01-01", "date": "2026-01-01"}, headers=headers
        ).status_code
        == 422
    )
    yearly = client.post("/api/occasions", json={"title": "Yearly Thing", "month_day": "12-25", "kind": "event"}, headers=headers)
    assert yearly.status_code == 200
    assert yearly.json()["recurrence"] == "yearly"
    once = client.post("/api/occasions", json={"title": "Once Thing", "date": "2026-10-01", "kind": "deadline"}, headers=headers)
    assert once.status_code == 200
    assert once.json()["recurrence"] == "once"


def test_occasion_private_to_user_is_hidden_from_other_users(client):
    """Two primary-side users would both be role='primary' only in theory —
    the guard is user-scoped, so test it with the requesting user vs another
    id (the surprise flag hides MY surprise for YOU from you)."""
    user_id = _primary()
    other_id = _partner()  # any other user id works for the flag
    headers = auth_headers(user_id)
    client.post("/api/occasions", json={"title": "Visible", "month_day": "06-01"}, headers=headers)
    client.post(
        "/api/occasions",
        json={"title": "Their Surprise", "month_day": "07-01", "private_to_user": other_id},
        headers=headers,
    )
    titles = [o["title"] for o in client.get("/api/occasions", headers=headers).json()]
    assert "Visible" in titles
    assert "Their Surprise" not in titles


# ------------------------------------------------------------------ gifts --
def test_gift_vault_status_flow(client):
    user_id = _primary()
    headers = auth_headers(user_id)
    person = client.post("/api/people", json={"name": "Gift Target"}, headers=headers).json()
    gift = client.post(
        "/api/gifts",
        json={"person_id": person["id"], "idea": "A synthetic thing", "price_pence": 2500},
        headers=headers,
    ).json()
    assert gift["status"] == "idea"

    bought = client.patch(f"/api/gifts/{gift['id']}", json={"status": "bought"}, headers=headers).json()
    assert bought["status"] == "bought"
    assert client.patch(f"/api/gifts/{gift['id']}", json={"status": "wrapped"}, headers=headers).status_code == 422

    listed = client.get(f"/api/gifts?person_id={person['id']}", headers=headers).json()
    assert len(listed) == 1 and listed[0]["status"] == "bought"


def test_gift_requires_existing_person(client):
    user_id = _primary()
    headers = auth_headers(user_id)
    assert client.post("/api/gifts", json={"person_id": 999, "idea": "x"}, headers=headers).status_code == 404


# ------------------------------------------- calendar birthday candidates --
def _seed_calendar_events():
    """Synthetic fixtures covering every title shape the matcher handles —
    including the real household's observed '<name> bday' suffix form."""
    from app.db import SessionLocal
    from app.models import CalendarEvent

    rows = [
        # the observed household shape: "Name bday"
        ("uid-1", "2026-08-14 00:00:00", "Kenji bday", "personal", 1),
        # classic possessive
        ("uid-2", "2026-09-03 00:00:00", "Aiko's Birthday", "personal", 1),
        # curly apostrophe
        ("uid-3", "2026-10-11 00:00:00", "Ren’s birthday", "shared", 1),
        # prefix form
        ("uid-4", "2026-11-02 00:00:00", "Birthday: Mio", "personal", 1),
        # Apple birthday-calendar event: bare name, calendar carries the signal
        ("uid-5", "2026-12-01 00:00:00", "Sora Fixture", "Birthdays", 1),
        # noise that must NOT surface
        ("uid-6", "2026-08-20 00:00:00", "Dentist", "personal", 0),
        ("uid-7", "2026-08-21 09:00:00", "Buy birthday card", "personal", 0),  # no name half
    ]
    with SessionLocal() as db:
        for uid, starts_at, title, cal, all_day in rows:
            db.add(CalendarEvent(ics_uid=uid, starts_at=starts_at, all_day=all_day, title=title, calendar_name=cal))
        db.commit()


def test_candidates_surface_birthday_shaped_events(client):
    user_id = _primary()
    headers = auth_headers(user_id)
    _seed_calendar_events()

    candidates = client.get("/api/people/candidates", headers=headers).json()
    by_name = {c["name"]: c for c in candidates}
    assert set(by_name) == {"Kenji", "Aiko", "Ren", "Mio", "Sora Fixture"}
    assert by_name["Kenji"]["month_day"] == "08-14"
    assert by_name["Sora Fixture"]["calendar_name"] == "Birthdays"
    # noise excluded
    assert "Dentist" not in by_name

    # nothing was created by scanning (suggestions only — HANDOFF Q8)
    assert client.get("/api/people", headers=headers).json() == []


def test_candidates_exclude_people_already_tracked(client):
    user_id = _primary()
    headers = auth_headers(user_id)
    _seed_calendar_events()
    client.post("/api/people", json={"name": "Kenji"}, headers=headers)

    names = [c["name"] for c in client.get("/api/people/candidates", headers=headers).json()]
    assert "Kenji" not in names
    assert "Aiko" in names


def test_confirm_candidate_creates_person_and_yearly_occasion(client):
    user_id = _primary()
    headers = auth_headers(user_id)
    _seed_calendar_events()

    res = client.post(
        "/api/people/candidates/confirm",
        json={"name": "Kenji", "month_day": "08-14", "relation": "friend"},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["person"]["name"] == "Kenji"
    assert body["person"]["birthday"] is None  # calendar knows the day, not the year
    assert body["occasion"]["kind"] == "birthday"
    assert body["occasion"]["recurrence"] == "yearly"
    assert body["occasion"]["month_day"] == "08-14"

    # confirming twice conflicts rather than duplicating
    assert (
        client.post(
            "/api/people/candidates/confirm", json={"name": "Kenji", "month_day": "08-14"}, headers=headers
        ).status_code
        == 409
    )
