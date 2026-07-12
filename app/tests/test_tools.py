from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.ai import tools
from app.core.config import get_settings

NZ = ZoneInfo(get_settings().restaurant_timezone)


def test_weekday_mismatch_flags_wrong_day():
    starts_at = datetime(2026, 7, 17, 19, 0, tzinfo=NZ)  # Friday
    result = tools._weekday_mismatch(starts_at, "Thursday")
    assert result is not None
    assert "Friday" in result["error"]
    assert "Thursday" in result["error"]


def test_weekday_mismatch_accepts_correct_day():
    starts_at = datetime(2026, 7, 16, 19, 0, tzinfo=NZ)  # Thursday
    assert tools._weekday_mismatch(starts_at, "Thursday") is None


def test_weekday_mismatch_is_case_insensitive():
    starts_at = datetime(2026, 7, 16, 19, 0, tzinfo=NZ)  # Thursday
    assert tools._weekday_mismatch(starts_at, "thursday") is None


def test_weekday_mismatch_skips_check_when_day_name_absent():
    starts_at = datetime(2026, 7, 17, 19, 0, tzinfo=NZ)  # Friday
    assert tools._weekday_mismatch(starts_at, None) is None


async def test_check_availability_rejects_mismatched_day_without_touching_db():
    result = await tools.check_availability(
        db=None, starts_at="2026-07-17T19:00:00+12:00", party_size=2, day_name="Thursday"
    )
    assert "error" in result
    assert "Friday" in result["error"]


def test_local_weekday_is_computed_not_guessed():
    starts_at = datetime(2026, 7, 17, 19, 0, tzinfo=NZ)  # Friday
    assert tools._local_weekday(starts_at) == "Friday"


async def test_create_reservation_rejects_mismatched_day_without_touching_db():
    result = await tools.create_reservation(
        db=None,
        phone_number="+6421000000",
        party_size=2,
        starts_at="2026-07-17T19:00:00+12:00",
        customer_name="Test Caller",
        day_name="Thursday",
    )
    assert result == {
        "error": (
            "2026-07-17 is a Friday, not Thursday. Re-check the calendar in "
            "the system prompt and pass the date from the row that actually "
            "has that weekday name."
        )
    }
