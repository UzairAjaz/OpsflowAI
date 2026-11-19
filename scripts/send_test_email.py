"""Send a real Phase 3 Gmail notification for the latest Retriva incident."""

from __future__ import annotations

import argparse

from sqlalchemy import select

from db.models import Incident
from db.session import SessionLocal
from integrations.notifications import send_gmail_event


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a test OpsFlow Gmail notification")
    parser.add_argument(
        "--event",
        choices=["pr_created", "resolved", "regressed"],
        default="pr_created",
    )
    args = parser.parse_args()

    with SessionLocal() as session:
        incident = session.execute(
            select(Incident)
            .where(Incident.tenant_id == "retriva")
            .order_by(Incident.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if incident is None:
            raise SystemExit("No Retriva incident found")

        result = send_gmail_event(
            event=args.event,
            incident=incident,
            pr_url=incident.pr_url,
            revert_pr_url=incident.revert_pr_url,
        )

    print(f"channel={result.channel} ok={result.ok} detail={result.detail}")
    if not result.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
