"""Does the unit discovery keep the right units and drop the rest."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import collect

CANDIDATES = ["T_CONSTRAINED-1", "T_OCCASIONAL-1", "T_ENERGYONLY-1", "T_NEVER-1"]


def fake_feed(monkeypatch):
    """Every day: one unit bid off for system reasons, one only on the first day,
    one bid off but never with the SO flag, and one that never appears at all."""

    def fetch(start_utc, end_utc, use_cache=True):
        day = start_utc.date()
        rows = [
            {"bmUnit": "T_CONSTRAINED-1", "soFlag": True},
            {"bmUnit": "T_ENERGYONLY-1", "soFlag": False},
        ]
        if day.day <= 2:
            rows.append({"bmUnit": "T_OCCASIONAL-1", "soFlag": True})
        return rows

    monkeypatch.setattr(collect, "fetch_boalf", fetch)


def test_keeps_units_bid_off_for_system_reasons(monkeypatch):
    fake_feed(monkeypatch)
    found = collect.discover_constrained_units("2026-01-01", "2026-01-31", CANDIDATES, min_days=3)
    assert found == ["T_CONSTRAINED-1"]


def test_energy_only_and_absent_units_are_dropped(monkeypatch):
    fake_feed(monkeypatch)
    found = collect.discover_constrained_units("2026-01-01", "2026-01-31", CANDIDATES, min_days=1)
    assert "T_ENERGYONLY-1" not in found
    assert "T_NEVER-1" not in found


def test_min_days_lets_occasional_units_back_in(monkeypatch):
    fake_feed(monkeypatch)
    found = collect.discover_constrained_units(
        "2026-01-01", "2026-01-31", CANDIDATES, min_days=1, sample_days=None
    )
    assert "T_OCCASIONAL-1" in found


def test_units_outside_the_candidate_list_are_ignored(monkeypatch):
    fake_feed(monkeypatch)
    found = collect.discover_constrained_units("2026-01-01", "2026-01-31", ["T_SOMETHINGELSE-1"], min_days=1)
    assert found == []
