"""Append-only hash-chained ledger of harness actions.

Each line is one action. The next line stores the previous line's hash.
A sidecar head records the length and the last hash so a truncated file
does not still verify. The ledger has no update and no delete.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from app.harness.codec import canonical, fingerprint, utcnow
from app.harness.errors import AuditIntegrityError
from app.harness.paper import ELIGIBLE_FOR_LIVE_TRADING, enforce_paper

_GENESIS = "0" * 64


class AuditLedger:
    def __init__(self, path: Path, clock: Callable[[], str] | None = None) -> None:
        self.path = Path(path)
        self.head_path = self.path.with_suffix(self.path.suffix + ".head.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock or utcnow
        self._lock = threading.Lock()
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")
        if not self.head_path.exists():
            self._write_head(0, _GENESIS)

    def append(
        self,
        *,
        run_id: str,
        agent_id: str,
        role: str,
        action: str,
        payload: Mapping[str, Any],
        decision: str,
        gate_approved: bool | None = None,
        budget_kind: str | None = None,
        budget_amount: int = 0,
    ) -> dict[str, Any]:
        enforce_paper(payload)
        body_input = {
            "run_id": run_id,
            "agent_id": agent_id,
            "role": role,
            "action": action,
            "input_hash": fingerprint(dict(payload)),
            "decision": decision,
            "gate_approved": gate_approved,
            "budget_kind": budget_kind,
            "budget_amount": int(budget_amount),
            "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        }
        with self._lock:
            count, previous = self._read_head()
            record = {
                "seq": count + 1,
                "ts": self._clock(),
                "prev_hash": previous,
                **body_input,
            }
            record["entry_hash"] = fingerprint({key: record[key] for key in record if key != "entry_hash"})
            line = canonical(record)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self._write_head(count + 1, str(record["entry_hash"]))
            return record

    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._lines()

    def verify(self) -> int:
        with self._lock:
            rows = self._lines()
            count, last = self._read_head()
            if count != len(rows):
                raise AuditIntegrityError(f"audit head count {count} does not match {len(rows)} rows")
            previous = _GENESIS
            for index, row in enumerate(rows, start=1):
                if row.get("seq") != index:
                    raise AuditIntegrityError(f"audit seq gap at {row.get('seq')}")
                if row.get("prev_hash") != previous:
                    raise AuditIntegrityError(f"audit prev_hash mismatch at seq {index}")
                if row.get("eligible_for_live_trading") is not False:
                    raise AuditIntegrityError("audit row claimed live trading")
                stored = row.get("entry_hash")
                check = {key: value for key, value in row.items() if key != "entry_hash"}
                if stored != fingerprint(check):
                    raise AuditIntegrityError(f"audit entry_hash mismatch at seq {index}")
                previous = str(stored)
            if previous != last:
                raise AuditIntegrityError("audit head hash does not match the last row")
            return len(rows)

    def _lines(self) -> list[dict[str, Any]]:
        text = self.path.read_text(encoding="utf-8")
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            parsed = json.loads(line)
            if not isinstance(parsed, dict):
                raise AuditIntegrityError("audit row is not an object")
            rows.append(parsed)
        return rows

    def _read_head(self) -> tuple[int, str]:
        if not self.head_path.exists():
            raise AuditIntegrityError("audit head is missing")
        raw = json.loads(self.head_path.read_text(encoding="utf-8"))
        if raw.get("eligible_for_live_trading") is not False:
            raise AuditIntegrityError("audit head claimed live trading")
        return int(raw["count"]), str(raw["last_hash"])

    def _write_head(self, count: int, last_hash: str) -> None:
        payload = {
            "count": count,
            "last_hash": last_hash,
            "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        }
        self.head_path.write_text(canonical(payload), encoding="utf-8")
