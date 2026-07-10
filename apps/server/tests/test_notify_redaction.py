"""The redaction gate — docs/ARCHITECTURE.md §5.2 (a HARD rule),
docs/phases/PHASE-5-notify.md acceptance: "a test template containing
'£1,234' or '6.2 hr' fails CI; runtime strip logged."

``check_redaction`` is the test-time half (raises); ``redact`` is the
runtime half (strips, never raises) — ``app.notify.send`` calls only the
latter, logging + sync_runs-noting any violation."""
from __future__ import annotations

import pytest

from app import notify


# ---------------------------------------------------------------- rejected --
@pytest.mark.parametrize(
    "text",
    [
        "House pot just crossed £1,234 today",
        "You've saved $5,000 this month",
        "Only 450 pence left in the jar",
        "You slept 6.2 hr last night",
        "Weighed in at 78.5 kg this morning",
        "Resting heart rate 62 bpm",
        "Burned 310 kcal on that run",
    ],
)
def test_check_redaction_rejects_money_and_health_shapes(text: str) -> None:
    with pytest.raises(notify.RedactionError):
        notify.check_redaction(text)


@pytest.mark.parametrize(
    "text",
    [
        "House pot just crossed £1,234 today",
        "You slept 6.2 hr last night",
    ],
)
def test_redact_strips_offending_spans_without_raising(text: str) -> None:
    safe, violations = notify.redact(text)
    assert violations  # non-empty: the caller (send()) logs + sync_runs-notes this
    assert "[redacted]" in safe
    # the original numeric/currency shape must not survive the strip
    assert "£1,234" not in safe
    assert "6.2 hr" not in safe


# ------------------------------------------------------------------ allowed --
@pytest.mark.parametrize(
    "text",
    [
        "Gym gap: 4 days — a walk on the way home?",
        "House pot just crossed another 5% 🎉",
        "Occasion in 21 days: Ken's birthday",
        "Morning briefing ready for 2026-07-10",
        "Streak sits at 12 days — studied today ✓",
        "3 nudges waiting for you",
    ],
)
def test_check_redaction_allows_day_counts_dates_percentages_and_small_ints(text: str) -> None:
    notify.check_redaction(text)  # must not raise


@pytest.mark.parametrize(
    "text",
    [
        "Gym gap: 4 days — a walk on the way home?",
        "House pot just crossed another 5% 🎉",
    ],
)
def test_redact_is_a_no_op_for_clean_text(text: str) -> None:
    safe, violations = notify.redact(text)
    assert violations == []
    assert safe == text
