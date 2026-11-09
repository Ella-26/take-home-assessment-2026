from datetime import datetime, timezone

from fix import deals_needing_followup

# Fixed "today" so every test gives the same result on any day it is run.
TODAY = datetime(2026, 11, 1, tzinfo=timezone.utc)


def test_excludes_closed():
    deals = [
        {"name": "A", "stage": "Closed - Won",
         "last_contact": "2026-09-01T09:00:00+08:00"},
    ]
    assert deals_needing_followup(deals, today=TODAY) == []


def test_stale_deal_returned():
    deals = [
        {"name": "B", "stage": "Diligence",
         "last_contact": "2026-10-01T09:30:00+08:00"},
    ]
    assert deals_needing_followup(deals, today=TODAY) == ["B"]


def test_no_shared_state():
    deals = [
        {"name": "C", "stage": "Sourcing",
         "last_contact": "2026-09-01T09:00:00+08:00"},
    ]
    deals_needing_followup(deals, today=TODAY)
    assert deals_needing_followup(deals, today=TODAY) == ["C"]


def test_mixed_offsets_sorted_most_stale_first():
    deals = [
        {"name": "India", "stage": "Sourcing",
         "last_contact": "2026-10-02T10:00:00+05:30"},
        {"name": "Singapore", "stage": "Sourcing",
         "last_contact": "2026-10-01T09:30:00+08:00"},
    ]
    result = deals_needing_followup(deals, today=TODAY)
    assert result == ["Singapore", "India"]


# --- New tests ---

def test_none_last_contact_returned_first_without_crash():
    # Bug 1: None becomes naive datetime.min, which crashes against aware today.
    deals = [
        {"name": "Stale", "stage": "Diligence",
         "last_contact": "2026-10-01T09:00:00+08:00"},
        {"name": "NeverContacted", "stage": "Sourcing",
         "last_contact": None},
    ]
    assert deals_needing_followup(deals, today=TODAY) == ["NeverContacted", "Stale"]


def test_same_date_mixed_offsets_sorted_by_actual_time():
    # Bug 2: 09:00+08:00 = 01:00 UTC is older than 08:00+05:30 = 02:30 UTC,
    # but sorting the raw strings puts "08:00" first.
    deals = [
        {"name": "India", "stage": "Sourcing",
         "last_contact": "2026-10-01T08:00:00+05:30"},
        {"name": "Singapore", "stage": "Sourcing",
         "last_contact": "2026-10-01T09:00:00+08:00"},
    ]
    assert deals_needing_followup(deals, today=TODAY) == ["Singapore", "India"]


def test_contact_14_5_days_ago_returned_recent_excluded():
    # Bug 3: 14.5 days ago gives .days == 14, so "> 14" misses it.
    deals = [
        {"name": "Stale14_5", "stage": "Diligence",
         "last_contact": "2026-10-17T20:00:00+08:00"},  # 14.5 days before TODAY
        {"name": "Recent", "stage": "Sourcing",
         "last_contact": "2026-10-30T09:00:00+08:00"},  # ~2 days before TODAY
    ]
    assert deals_needing_followup(deals, today=TODAY) == ["Stale14_5"]
