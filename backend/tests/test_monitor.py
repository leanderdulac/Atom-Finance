"""Monitor evaluation: transitions, conservative gaps, alerts, stability."""
import pytest

from app.models.monitor import evaluate, validate_geometry

DAY0 = "2026-01-05T12:00:00+00:00"
DAY1 = "2026-01-06T12:00:00+00:00"
DAY9 = "2026-01-14T12:00:00+00:00"


def _mon(**kw):
    base = {"direction": "long", "entry": 100.0, "stop": 95.0, "target": 110.0,
            "declared_at": DAY0, "horizon_days": 10, "state": "watching",
            "last_spot": None, "entered_at": None, "entry_px": None}
    base.update(kw)
    return base


def test_validate_geometry():
    validate_geometry("long", 100, 95, 110)
    validate_geometry("short", 100, 105, 90)
    with pytest.raises(ValueError, match="stop < entry < target"):
        validate_geometry("long", 100, 105, 110)
    with pytest.raises(ValueError, match="target < entry < stop"):
        validate_geometry("short", 100, 105, 110)
    with pytest.raises(ValueError, match="direction"):
        validate_geometry("flat", 100, 95, 110)
    with pytest.raises(ValueError, match="positive"):
        validate_geometry("long", 100, 95, float("nan"))


def test_watching_enters_on_cross_and_reports():
    out = evaluate(_mon(last_spot=99.0), 100.5, DAY1)
    assert out["state"] == "active"
    assert out["entered_at"] == DAY1
    assert out["entry_px"] == 100.0
    assert [a["kind"] for a in out["alerts"]] == ["entered"]


def test_watching_first_sight_far_stays_watching():
    out = evaluate(_mon(), 90.0, DAY1)
    assert out["state"] == "watching"
    assert out["entered_at"] is None


def test_watching_first_sight_near_fills_with_note():
    out = evaluate(_mon(), 100.2, DAY1)
    assert out["state"] == "active"
    assert out["entry_px"] == 100.0


def test_watching_expires_unfilled():
    out = evaluate(_mon(), 90.0, "2026-01-20T12:00:00+00:00")
    assert out["state"] == "expired"
    assert out["pnl_pct"] is None
    assert out["exit_reason"]


def test_active_stop_and_target_with_pnl():
    active = _mon(state="active", last_spot=100.0, entered_at=DAY0, entry_px=100.0)
    stopped = evaluate(dict(active), 94.0, DAY1)
    assert stopped["state"] == "stopped"
    assert stopped["exit_px"] == 95.0
    assert stopped["pnl_pct"] == -5.0
    hit = evaluate(dict(active), 111.0, DAY1)
    assert hit["state"] == "target_hit"
    assert hit["pnl_pct"] == 10.0


def test_active_expiry_marks_to_market():
    active = _mon(state="active", last_spot=102.0, entered_at=DAY0, entry_px=100.0)
    out = evaluate(dict(active), 103.0, "2026-01-20T12:00:00+00:00")
    assert out["state"] == "expired"
    assert out["exit_px"] == 103.0
    assert out["pnl_pct"] == 3.0


def test_gap_crossing_both_resolves_to_stop():
    # Jumped over the whole range between checks: conservative stop wins.
    active = _mon(state="active", last_spot=99.0, entered_at=DAY0, entry_px=100.0)
    out = evaluate(dict(active), 115.0, DAY1)
    assert out["state"] in ("stopped", "target_hit")
    # Long stop is below: a jump up cannot stop it — target wins instead.
    assert out["state"] == "target_hit"
    short = _mon(direction="short", entry=100.0, stop=105.0, target=90.0,
                 state="active", last_spot=101.0, entered_at=DAY0, entry_px=100.0)
    out = evaluate(dict(short), 86.0, DAY1)
    # Jumped down past target: short target wins (stop is above).
    assert out["state"] == "target_hit"


def test_gap_up_through_short_stop_is_conservative():
    short = _mon(direction="short", entry=100.0, stop=105.0, target=90.0,
                 state="active", last_spot=99.0, entered_at=DAY0, entry_px=100.0)
    out = evaluate(dict(short), 120.0, DAY1)
    assert out["state"] == "stopped"
    assert out["pnl_pct"] == -5.0


def test_near_and_time_alerts():
    active = _mon(state="active", last_spot=96.0, entered_at=DAY0, entry_px=100.0)
    out = evaluate(dict(active), 95.8, DAY1)
    kinds = [a["kind"] for a in out["alerts"]]
    assert "near_stop" in kinds
    late = _mon(state="active", last_spot=102.0, entered_at=DAY0, entry_px=100.0)
    out = evaluate(dict(late), 102.0, DAY9)
    assert "time_running_out" in [a["kind"] for a in out["alerts"]]


def test_oracle_flags_surface_as_alerts():
    active = _mon(state="active", last_spot=100.0, entered_at=DAY0, entry_px=100.0)
    out = evaluate(dict(active), 100.5, DAY1,
                   oracle={"stale": True, "usable": False, "disagreement_bps": 120.0})
    kinds = [a["kind"] for a in out["alerts"]]
    assert "quote_stale" in kinds
    assert "quotes_disagree" in kinds


def test_terminal_states_are_stable():
    done = _mon(state="target_hit", last_spot=111.0, entered_at=DAY0, entry_px=100.0)
    out = evaluate(dict(done), 50.0, "2027-01-01T00:00:00+00:00")
    assert out["state"] == "target_hit"
    assert out["alerts"] == []


def test_rejects_bad_spot_and_state():
    with pytest.raises(ValueError, match="spot"):
        evaluate(_mon(), float("nan"), DAY1)
    with pytest.raises(ValueError, match="unknown monitor state"):
        evaluate(_mon(state="flying"), 100.0, DAY1)
