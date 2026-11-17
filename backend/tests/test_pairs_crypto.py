"""ETH/SOL audit + info features + regime veto. Paper only. No network."""
import json
from pathlib import Path

from app.models.pairs_crypto import (
    FAMILY_ID,
    default_fixture_dir,
    load_panel,
    render_crypto_report_md,
    run_crypto_audit,
    write_crypto_report,
)
from app.models.pairs_meta import round_trip_cost
from app.models.pairs_real import CRYPTO_COMMISSION, CRYPTO_SLIPPAGE

FIXTURES = default_fixture_dir()
REPO = Path(__file__).resolve().parents[2]


def test_panel_fixture_has_spot_flow_and_funding():
    panel = load_panel(FIXTURES)
    assert panel["eligible_for_live_trading"] is False
    assert len(panel["eth"]["dates"]) >= 120
    assert len(panel["eth"]["taker_buy"]) == len(panel["eth"]["close"])
    assert len(panel["funding_eth"]) >= 200  # OKX~90 days; HL fills from 2023-05
    assert min(panel["funding_eth"]) <= "2023-06-01"
    assert "Hyperliquid" in panel["sources"]["funding_oi"]


def test_audit_registers_four_variants_and_stays_paper():
    out = run_crypto_audit(fixture_dir=FIXTURES)
    assert out["eligible_for_live_trading"] is False
    assert out["family_id"] == FAMILY_ID
    assert out["n_trials_registered"] == 4
    assert set(out["variants"]) == {
        "primary",
        "meta_candles",
        "meta_info_features",
        "meta_regime_veto",
    }
    assert out["audit"]["funding_in_spot_pnl"] is False
    assert out["audit"]["pnl_unit"] == "gross_two_leg_notional"
    assert out["costs"]["round_trip_gross"] == round_trip_cost(CRYPTO_COMMISSION, CRYPTO_SLIPPAGE)
    assert abs(out["costs"]["round_trip_gross"] - 0.0024) < 1e-12
    for gate in out["gates"].values():
        assert gate["costs_included"] is True
        assert gate["n_trials"] == 4.0
        if gate["approved"]:
            assert gate["dsr"] >= 0.95
        else:
            assert gate["dsr"] is None or gate["dsr"] < 0.95 or gate["reasons"]
    # Overlap is material; the unit bug is the +7% story, not "quase sem overlap".
    assert out["audit"]["n_overlapping"] >= 10
    assert out["audit"]["n_events"] > out["audit"]["n_overlapping"]
    occ = out["audit"]["occupied"]
    assert occ["n"] < out["audit"]["n_events"]
    legacy = out["audit"]["legacy_beta_times_return"]["net_per_trade"]
    audited = out["audit"]["audited_net_per_trade"]
    assert legacy is not None and audited is not None
    assert abs(legacy) > abs(audited) * 5


def test_committed_audit_report_matches_fixtures():
    committed = json.loads(
        (REPO / "docs/reports/pairs-eth-sol-audit-oos.json").read_text(encoding="utf-8")
    )
    fresh = run_crypto_audit(fixture_dir=FIXTURES)
    assert committed["n_trials_registered"] == fresh["n_trials_registered"]
    assert committed["eligible_for_live_trading"] is False
    assert committed["variants"] == fresh["variants"]
    assert committed["gates"]["primary"]["dsr"] == fresh["gates"]["primary"]["dsr"]
    assert committed["gates"]["meta_info_features"]["approved"] == fresh["gates"]["meta_info_features"]["approved"]
    assert committed["audit"]["audited_net_per_trade"] == fresh["audit"]["audited_net_per_trade"]
    md = (REPO / "docs/reports/pairs-eth-sol-audit-oos.md").read_text(encoding="utf-8")
    assert "eligible_for_live_trading" in md
    assert "quase sem overlap" not in md
    assert "Hyperliquid" in md
    assert "Nenhuma variante passou" in md or "não passou" in md


def test_report_writer_is_json_finite(tmp_path):
    out = run_crypto_audit(fixture_dir=FIXTURES)
    md_path, json_path = write_crypto_report(out, tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["eligible_for_live_trading"] is False
    dumped = json_path.read_text(encoding="utf-8")
    assert "NaN" not in dumped
    assert "Infinity" not in dumped
    md = render_crypto_report_md(out)
    assert "portão" in md.lower() or "DSR" in md
    assert md_path.exists()
