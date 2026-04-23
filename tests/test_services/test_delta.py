import pytest
from datetime import datetime
from app.services.delta import compute_deltas, format_delta_for_prompt


def test_compute_deltas_detects_significant_egfr_drop():
    snapshots = [
        {"recorded_at": datetime(2026, 4, 1), "lab_values": {"egfr": 40.0}},
        {"recorded_at": datetime(2026, 3, 1), "lab_values": {"egfr": 55.0}},
        {"recorded_at": datetime(2026, 2, 1), "lab_values": {"egfr": 60.0}},
    ]
    deltas = compute_deltas(snapshots)
    assert len(deltas) == 2
    first = deltas[0]["deltas"]["egfr"]
    assert first["delta"] == pytest.approx(-15.0)
    assert first["significant"] is True
    assert first["direction"] == "down"


def test_compute_deltas_not_significant_for_small_change():
    snapshots = [
        {"recorded_at": datetime(2026, 4, 1), "lab_values": {"egfr": 58.0}},
        {"recorded_at": datetime(2026, 3, 1), "lab_values": {"egfr": 60.0}},
    ]
    deltas = compute_deltas(snapshots)
    assert deltas[0]["deltas"]["egfr"]["significant"] is False


def test_compute_deltas_returns_empty_for_single_snapshot():
    snapshots = [
        {"recorded_at": datetime(2026, 4, 1), "lab_values": {"egfr": 55.0}},
    ]
    assert compute_deltas(snapshots) == []


def test_format_delta_for_prompt_includes_egfr_and_values():
    snapshots = [
        {"recorded_at": datetime(2026, 4, 1), "lab_values": {"egfr": 40.0}},
        {"recorded_at": datetime(2026, 3, 1), "lab_values": {"egfr": 60.0}},
    ]
    result = format_delta_for_prompt(snapshots)
    assert "egfr" in result.lower() or "eGFR" in result
    assert "40" in result
    assert "60" in result


def test_format_delta_for_prompt_with_current_lab_prepended():
    snapshots = [
        {"recorded_at": datetime(2026, 3, 1), "lab_values": {"egfr": 55.0}},
    ]
    current = {"egfr": 40.0}
    result = format_delta_for_prompt(snapshots, current_lab=current)
    assert "40" in result
    assert "55" in result
