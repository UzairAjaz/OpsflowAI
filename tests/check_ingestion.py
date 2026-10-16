"""P2-06 check: alert idempotency and deduplication.

Verifies:
- a first alert is reported as "new",
- an exact replay is reported as "duplicate" and increments the count,
- a burst of alerts for the same service/error class within the window is
  reported as "merged" (no additional new incidents),
- normalization rejects payloads missing required fields.
"""

from __future__ import annotations

from sqlalchemy import delete, select

from db.models import ProcessedAlert
from db.session import SessionLocal
from ingestion.schema import AlertValidationError, normalize_alert
from ingestion.service import process_alert

SERVICE = "ingest-check-svc"
ERROR_CLASS = "OOMKilled"


def _payload(n: int) -> dict:
    return {
        "source": "cloudwatch",
        "service": SERVICE,
        "error_class": ERROR_CLASS,
        "severity_hint": "critical",
        "raw_log": f"event {n}",
    }


def _cleanup() -> None:
    with SessionLocal() as session:
        session.execute(delete(ProcessedAlert).where(ProcessedAlert.service == SERVICE))
        session.commit()


def main() -> None:
    _cleanup()
    try:
        with SessionLocal() as session:
            first = process_alert(session, _payload(0))
            assert first.action == "new", first.action
            print("first alert   ->", first.action)

            replay = process_alert(session, _payload(0))
            assert replay.action == "duplicate", replay.action
            print("exact replay  ->", replay.action)

            row = session.execute(
                select(ProcessedAlert).where(
                    ProcessedAlert.alerts_signature == first.alert.alerts_signature
                )
            ).scalar_one()
            assert row.count == 2, row.count
            print("replay count  ->", row.count)

            actions = {"new": 0, "merged": 0, "duplicate": 0}
            for n in range(1, 500):
                result = process_alert(session, _payload(n))
                actions[result.action] += 1
            print("burst of 499  ->", actions)
            assert actions["new"] == 0, "burst must not create new groups"
            assert actions["merged"] == 499, actions

        try:
            normalize_alert({"service": "x"})
            raise AssertionError("expected AlertValidationError")
        except AlertValidationError:
            print("validation    -> missing 'source' rejected as expected")

        print("[ok] P2-06 -- idempotency and deduplication working.")
    finally:
        _cleanup()


if __name__ == "__main__":
    main()
