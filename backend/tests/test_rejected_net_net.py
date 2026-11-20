"""The discarded B3 net-net search is in the trial ledger. No network."""
import inspect
import json

from app.models.afml.gate import gate_trial
from app.models.afml.trials import TrialRegistry
from app.models.rejected_net_net import (
    FAMILY_ID,
    REPORT_PATH,
    catalog,
    record_rejected_net_nets,
    rejected_ledger_count,
)


def test_catalog_keeps_the_published_negative_metrics():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    rows = catalog()
    assert report["family_id"] == FAMILY_ID
    assert report["eligible_for_live_trading"] is False
    assert report["n_trials"] == 32
    assert rejected_ledger_count() == 32
    assert len({row["record_key"] for row in rows}) == 32
    sample = report["sample"]
    for src, rec in zip(report["trials"], rows, strict=True):
        assert rec["status"] == "rejected"
        assert rec["eligible_for_live_trading"] is False
        assert rec["sharpe"] == src["sharpe_net"]
        assert rec["psr"] == src["psr"]
        assert rec["dsr"] == src["dsr"]
        assert rec["min_trl_months"] == src["min_trl_months"]
        assert rec["min_trl_infinite"] is src["min_trl_infinite"]
        assert rec["cagr_gross"] == src["cagr_gross"]
        assert rec["cagr_net"] == src["cagr_net"]
        assert rec["n_obs_months"] == src["n_obs_months"]
        assert rec["sample_first_session"] == sample["first_session"]
        assert rec["sample_last_session"] == sample["last_session"]
        assert rec["sample_first_signal_on_or_after"] == sample["first_signal_on_or_after"]
        assert rec["block"] == src["block"]
        assert rec["filter"] == src["filter"]
        assert rec["yield_proxy"] == src["yield_proxy"]
        assert rec["lag_days"] == src["lag_days"]
        assert rec["phase"] == src["phase"]
        assert rec["aum_brl"] == src["aum_brl"]


def test_registry_seeds_rejected_trials_once_and_later_dsr_counts_them(tmp_path):
    path = tmp_path / "trials.sqlite"
    with TrialRegistry(path) as reg:
        assert record_rejected_net_nets(reg) == 32
        assert reg.count(FAMILY_ID) == 32
        stored = reg.trials(FAMILY_ID)
        assert len(stored) == 32
        assert all(trial.status == "rejected" for trial in stored)
        assert all(trial.notes == "rejected" for trial in stored)
        assert all(trial.costs_included is True for trial in stored)
        assert all(trial.periods_per_year == 12.0 for trial in stored)
        by_key = {trial.params["record_key"]: trial for trial in stored}
        for rec in catalog():
            trial = by_key[rec["record_key"]]
            assert trial.sharpe == rec["sharpe"]
            assert trial.n_obs == rec["n_obs_months"]
            assert trial.params["psr"] == rec["psr"]
            assert trial.params["dsr"] == rec["dsr"]
            assert trial.params["min_trl_months"] == rec["min_trl_months"]
            assert trial.params["cagr_gross"] == rec["cagr_gross"]
            assert trial.params["cagr_net"] == rec["cagr_net"]
            assert trial.params["sample_first_session"] == "2011-01-03"
            assert trial.params["sample_last_session"] == "2026-11-19"
            assert trial.params["sample_first_signal_on_or_after"] == "2012-05-02"
            verdict = gate_trial(reg, FAMILY_ID, costs_included=True, trial_id=trial.id)
            assert verdict.n_trials == 32
            assert verdict.approved is False
        reg.register("later", {"i": 1}, sharpe=1.0, n_obs=100, costs_included=True)
        later = gate_trial(reg, "later", costs_included=True)
        assert later.n_trials == 1 + 32
    with TrialRegistry(path) as reg:
        assert reg.count(FAMILY_ID) == 32
        assert reg.count() == 33


def test_recorder_does_not_touch_the_network():
    import app.models.rejected_net_net as mod

    src = inspect.getsource(mod)
    for token in ("urllib", "requests", "httpx", "socket", "urlopen"):
        assert token not in src
    assert "app.models.net_net" not in src
