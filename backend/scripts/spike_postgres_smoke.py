"""SPIKE smoke test — exercises database_pg.py against a real Postgres.

Not part of the pytest suite (needs a live Postgres + ATOM_DATABASE_URL).
Run: ATOM_DATABASE_URL=postgresql+asyncpg://... python scripts/spike_postgres_smoke.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import database_pg as db  # noqa: E402


async def main():
    print("1. create_user...")
    uid = await db.create_user("spike_alice", "alice@spike.test", "fakehash123")
    assert uid is not None, "expected a new user id"
    print(f"   OK, id={uid}")

    print("2. create_user duplicate rejected...")
    dup = await db.create_user("spike_alice", "alice2@spike.test", "fakehash123")
    assert dup is None, "expected duplicate username to be rejected"
    print("   OK, duplicate correctly rejected")

    print("3. get_user_by_username...")
    user = await db.get_user_by_username("spike_alice")
    assert user is not None and user["email"] == "alice@spike.test"
    print(f"   OK, {user}")

    print("4. user_exists...")
    assert await db.user_exists("spike_alice") is True
    assert await db.user_exists("nobody_here") is False
    print("   OK")

    print("5. save_report (JSONB round-trip)...")
    report = {
        "recommendation": {"bull_score": 78.5, "action": "COMPRAR CALL"},
        "market_data": {"price": 38.5, "currency": "BRL"},
        "narrative": "Teste de spike — não é recomendação real.",
        "nested": {"a": [1, 2, 3], "b": None},
    }
    report_id = await db.save_report("PETR4", report, owner="spike_alice")
    print(f"   OK, id={report_id}")

    print("6. get_report_by_id (JSONB decode)...")
    fetched = await db.get_report_by_id(report_id, owner="spike_alice")
    assert fetched == report, f"round-trip mismatch: {fetched} != {report}"
    print("   OK, full JSONB round-trip matches exactly")

    print("7. list_reports...")
    reports = await db.list_reports(owner="spike_alice")
    assert len(reports) == 1 and reports[0]["ticker"] == "PETR4"
    print(f"   OK, {reports}")

    print("8. list_reports filtered by ticker (no match)...")
    empty = await db.list_reports(ticker="VALE3", owner="spike_alice")
    assert empty == []
    print("   OK")

    print("9. readiness() (probe write must roll back)...")
    await db.readiness()
    pool = await db.get_pool()
    count = await pool.fetchval("SELECT COUNT(*) FROM health_probe")
    assert count == 0, f"expected the probe row to be rolled back, found {count} row(s)"
    print("   OK, probe write rolled back as expected")

    await db.close_pool()
    print("\nAll spike checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
