"""Real-data pairs universe: fixtures, honest N, DSR gate. Paper only. No network."""
import json
from pathlib import Path

from app.models.pairs_real import (
    FAMILY_ID,
    UNIVERSE,
    default_fixture_dir,
    load_ticker,
    render_real_report_md,
    run_real_universe,
    write_real_report,
)

FIXTURES = default_fixture_dir()
REPO = Path(__file__).resolve().parents[2]


def test_universe_is_fixed_by_thesis_before_results():
    ids = [p["pair_id"] for p in UNIVERSE]
    assert ids == [
        "PETR3_PETR4",
        "CMIG3_CMIG4",
        "ITUB4_BBDC4",
        "GGBR4_USIM5",
        "VALE3_CSNA3",
        "ETHUSDT_SOLUSDT",
    ]
    assert all(p["thesis"].strip() for p in UNIVERSE)
    assert {p["venue"] for p in UNIVERSE} == {"B3", "crypto_spot"}


def test_fixtures_cover_every_leg_and_are_daily():
    assert (FIXTURES / "manifest.json").exists()
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    for spec in UNIVERSE:
        for leg in (spec["y"], spec["x"]):
            blob = load_ticker(FIXTURES, leg)
            assert len(blob["close"]) >= 120
            assert blob["interval"] == "1d"
            assert blob["dates"][0] <= blob["dates"][-1]
            assert blob["ticker"] == leg
            assert manifest["tickers"][leg]["n"] == len(blob["close"])


def test_run_registers_every_pair_variant_and_stays_paper():
    out = run_real_universe(fixture_dir=FIXTURES)
    assert out["eligible_for_live_trading"] is False
    assert out["family_id"] == FAMILY_ID
    assert out["n_pairs_tested"] == len(UNIVERSE)
    assert out["n_trials_registered"] == 2 * len(UNIVERSE)
    assert out["n_trials_registered"] == out["n_trials_expected"]
    pair_ids = [p["pair_id"] for p in out["pairs"]]
    assert pair_ids == [p["pair_id"] for p in UNIVERSE]
    registered_pairs = {t["pair_id"] for t in out["registered_trials"]}
    assert registered_pairs == set(pair_ids)
    variants = {t["variant"] for t in out["registered_trials"]}
    assert variants == {"primary_triple_barrier", "meta_filtered"}
    gate = out["gate"]
    assert gate["costs_included"] is True
    assert gate["n_trials"] == float(out["n_trials_registered"])
    assert gate["dsr"] is not None
    if gate["approved"]:
        assert gate["dsr"] >= 0.95
    else:
        assert gate["dsr"] < 0.95 or gate["reasons"]
    # Non-cointegrated pairs must still appear (no cherry-pick).
    assert any(not p["cointegrated_oos"] for p in out["pairs"])


def test_committed_real_report_matches_fixtures():
    committed = json.loads(
        (REPO / "docs/reports/pairs-meta-label-oos-real.json").read_text(encoding="utf-8")
    )
    fresh = run_real_universe(fixture_dir=FIXTURES)
    assert committed["n_trials_registered"] == fresh["n_trials_registered"]
    assert committed["gate"]["dsr"] == fresh["gate"]["dsr"]
    assert committed["gate"]["approved"] == fresh["gate"]["approved"]
    assert committed["eligible_for_live_trading"] is False
    for a, b in zip(committed["pairs"], fresh["pairs"], strict=True):
        assert a["pair_id"] == b["pair_id"]
        assert a["primary"] == b["primary"]
        assert a["filtered"] == b["filtered"]
        assert a["cointegrated_oos"] == b["cointegrated_oos"]
    md = (REPO / "docs/reports/pairs-meta-label-oos-real.md").read_text(encoding="utf-8")
    assert "eligible_for_live_trading" in md
    assert "PETR3_PETR4" in md
    assert "ETHUSDT_SOLUSDT" in md
    assert "Yahoo" in md or "yahoo" in md.lower()
    assert "Binance" in md


def test_report_writer_is_json_finite(tmp_path):
    out = run_real_universe(fixture_dir=FIXTURES)
    md_path, json_path = write_real_report(out, tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["eligible_for_live_trading"] is False
    md = render_real_report_md(out)
    assert "portão" in md.lower() or "DSR" in md
    assert md_path.exists()
    # No NaN in the public JSON.
    dumped = json_path.read_text(encoding="utf-8")
    assert "NaN" not in dumped
    assert "Infinity" not in dumped


def test_align_rejects_short_series():
    import pytest

    from app.models.pairs_real import align_pair

    short = {"ticker": "A", "dates": ["2020-01-01"], "close": [1.0]}
    with pytest.raises(ValueError, match="Alinhamento"):
        align_pair(short, short)
