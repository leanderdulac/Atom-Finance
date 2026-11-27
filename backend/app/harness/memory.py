"""Cross-run research memory.

SQLite, one file, shared by later runs of the same harness directory.
A fingerprint is stored once. A rejected hypothesis stays rejected.
``eligible_for_live_trading`` is a checked column that only accepts 0.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.harness.codec import as_json, feature_fingerprint, utcnow
from app.harness.errors import PaperViolation
from app.harness.paper import ELIGIBLE_FOR_LIVE_TRADING

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hypotheses (
    fingerprint TEXT PRIMARY KEY,
    family TEXT NOT NULL,
    statement TEXT NOT NULL,
    status TEXT NOT NULL,
    failure_kind TEXT,
    sharpe REAL,
    n_obs INTEGER,
    n_trials INTEGER,
    detail_json TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    eligible_for_live_trading INTEGER NOT NULL DEFAULT 0 CHECK (eligible_for_live_trading = 0)
);
CREATE TABLE IF NOT EXISTS features (
    fingerprint TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    formula TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    eligible_for_live_trading INTEGER NOT NULL DEFAULT 0 CHECK (eligible_for_live_trading = 0)
);
CREATE TABLE IF NOT EXISTS failure_modes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS patterns (
    fingerprint TEXT PRIMARY KEY,
    family TEXT NOT NULL,
    name TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    eligible_for_live_trading INTEGER NOT NULL DEFAULT 0 CHECK (eligible_for_live_trading = 0)
);
CREATE INDEX IF NOT EXISTS idx_hypotheses_family ON hypotheses(family);
CREATE TRIGGER IF NOT EXISTS hypotheses_paper_lock
BEFORE UPDATE ON hypotheses
WHEN NEW.eligible_for_live_trading != 0
BEGIN
    SELECT RAISE(ABORT, 'eligible_for_live_trading must remain false');
END;
CREATE TRIGGER IF NOT EXISTS hypotheses_no_promotion_after_reject
BEFORE UPDATE ON hypotheses
WHEN OLD.status = 'rejected' AND NEW.status != 'rejected'
BEGIN
    SELECT RAISE(ABORT, 'rejected hypothesis cannot be promoted');
END;
CREATE TRIGGER IF NOT EXISTS patterns_paper_lock
BEFORE UPDATE ON patterns
WHEN NEW.eligible_for_live_trading != 0
BEGIN
    SELECT RAISE(ABORT, 'eligible_for_live_trading must remain false');
END;
"""

_TERMINAL = frozenset({"rejected", "promoted_paper", "pruned"})


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    fingerprint: str
    family: str
    statement: str
    status: str
    failure_kind: str | None
    detail: dict[str, Any]
    run_id: str
    eligible_for_live_trading: bool = False

    def __post_init__(self) -> None:
        if self.eligible_for_live_trading is not False or ELIGIBLE_FOR_LIVE_TRADING is not False:
            raise PaperViolation("eligible_for_live_trading must remain false")


class ResearchMemory:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def lookup(self, fingerprint: str) -> MemoryRecord | None:
        with self._lock:
            return self._lookup(fingerprint)

    def count_family(self, family: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM hypotheses WHERE family = ?",
                (family.strip().lower(),),
            ).fetchone()
            return int(row["n"])

    def dead_features(self, names: tuple[str, ...], formulas: tuple[str, ...]) -> list[str]:
        hits: list[str] = []
        with self._lock:
            for name, formula in zip(names, formulas, strict=True):
                key = feature_fingerprint(name, formula)
                row = self._conn.execute(
                    "SELECT name FROM features WHERE fingerprint = ? AND status = 'dead'",
                    (key,),
                ).fetchone()
                if row is not None:
                    hits.append(str(row["name"]))
        return hits

    def is_finished(self, fingerprint: str) -> bool:
        record = self.lookup(fingerprint)
        return record is not None and record.status in _TERMINAL

    def reject(
        self,
        *,
        fingerprint: str,
        family: str,
        statement: str,
        failure_kind: str,
        reasons: tuple[str, ...] | list[str],
        run_id: str,
        sharpe: float | None,
        n_obs: int | None,
        n_trials: int | None,
        feature_names: tuple[str, ...] = (),
        feature_formulas: tuple[str, ...] = (),
        mark_features_dead: bool = False,
    ) -> MemoryRecord:
        detail = {
            "reasons": list(reasons),
            "failure_kind": failure_kind,
            "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        }
        with self._lock:
            existing = self._lookup(fingerprint)
            if existing is not None:
                return existing
            self._insert_hypothesis(
                fingerprint=fingerprint,
                family=family,
                statement=statement,
                status="rejected",
                failure_kind=failure_kind,
                sharpe=sharpe,
                n_obs=n_obs,
                n_trials=n_trials,
                detail=detail,
                run_id=run_id,
            )
            self._conn.execute(
                "INSERT INTO failure_modes (fingerprint, kind, detail, run_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (fingerprint, failure_kind, as_json(detail), run_id, utcnow()),
            )
            if mark_features_dead:
                self._mark_dead(feature_names, feature_formulas, run_id, failure_kind)
            self._conn.commit()
            stored = self._lookup(fingerprint)
        if stored is None:
            raise PaperViolation("rejected hypothesis was not stored")
        return stored

    def promote(
        self,
        *,
        fingerprint: str,
        family: str,
        statement: str,
        reasons: tuple[str, ...] | list[str],
        run_id: str,
        sharpe: float | None,
        n_obs: int | None,
        n_trials: int | None,
        dsr: float | None,
    ) -> MemoryRecord:
        detail = {
            "reasons": list(reasons),
            "dsr": dsr,
            "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        }
        with self._lock:
            existing = self._lookup(fingerprint)
            if existing is not None:
                return existing
            self._insert_hypothesis(
                fingerprint=fingerprint,
                family=family,
                statement=statement,
                status="promoted_paper",
                failure_kind=None,
                sharpe=sharpe,
                n_obs=n_obs,
                n_trials=n_trials,
                detail=detail,
                run_id=run_id,
            )
            self._conn.execute(
                "INSERT INTO patterns (fingerprint, family, name, payload_json, run_id, created_at, eligible_for_live_trading)"
                " VALUES (?, ?, ?, ?, ?, ?, 0)",
                (fingerprint, family.strip().lower(), statement[:120], as_json(detail), run_id, utcnow()),
            )
            self._conn.commit()
            stored = self._lookup(fingerprint)
        if stored is None:
            raise PaperViolation("promoted pattern was not stored")
        return stored

    def failure_modes(self, fingerprint: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT kind, detail, run_id FROM failure_modes WHERE fingerprint = ? ORDER BY id",
                (fingerprint,),
            ).fetchall()
        return [{"kind": row["kind"], "detail": json.loads(row["detail"]), "run_id": row["run_id"]} for row in rows]

    def _insert_hypothesis(
        self,
        *,
        fingerprint: str,
        family: str,
        statement: str,
        status: str,
        failure_kind: str | None,
        sharpe: float | None,
        n_obs: int | None,
        n_trials: int | None,
        detail: dict[str, Any],
        run_id: str,
    ) -> None:
        if detail.get("eligible_for_live_trading") is not False:
            raise PaperViolation("eligible_for_live_trading must remain false")
        self._conn.execute(
            """
            INSERT INTO hypotheses (
                fingerprint, family, statement, status, failure_kind, sharpe, n_obs, n_trials,
                detail_json, run_id, created_at, eligible_for_live_trading
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                fingerprint,
                family.strip().lower(),
                statement,
                status,
                failure_kind,
                sharpe,
                n_obs,
                n_trials,
                as_json(detail),
                run_id,
                utcnow(),
            ),
        )

    def _mark_dead(self, names: tuple[str, ...], formulas: tuple[str, ...], run_id: str, reason: str) -> None:
        for name, formula in zip(names, formulas, strict=True):
            self._conn.execute(
                """
                INSERT OR IGNORE INTO features (
                    fingerprint, name, formula, status, reason, run_id, created_at, eligible_for_live_trading
                ) VALUES (?, ?, ?, 'dead', ?, ?, ?, 0)
                """,
                (feature_fingerprint(name, formula), name, formula, reason, run_id, utcnow()),
            )

    def _lookup(self, fingerprint: str) -> MemoryRecord | None:
        row = self._conn.execute("SELECT * FROM hypotheses WHERE fingerprint = ?", (fingerprint,)).fetchone()
        if row is None:
            return None
        if int(row["eligible_for_live_trading"]) != 0:
            raise PaperViolation("eligible_for_live_trading must remain false")
        detail = json.loads(row["detail_json"])
        if not isinstance(detail, dict) or detail.get("eligible_for_live_trading", False) is not False:
            raise PaperViolation("eligible_for_live_trading must remain false")
        return MemoryRecord(
            fingerprint=str(row["fingerprint"]),
            family=str(row["family"]),
            statement=str(row["statement"]),
            status=str(row["status"]),
            failure_kind=None if row["failure_kind"] is None else str(row["failure_kind"]),
            detail=detail,
            run_id=str(row["run_id"]),
        )
