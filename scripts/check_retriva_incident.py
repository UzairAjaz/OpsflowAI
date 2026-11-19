"""Print the latest Retriva code-alert incident for local verification."""

from __future__ import annotations

import json

from sqlalchemy import select

from db.models import Incident
from db.session import SessionLocal


def main() -> None:
    with SessionLocal() as session:
        incident = session.execute(
            select(Incident)
            .where(Incident.tenant_id == "retriva")
            .order_by(Incident.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if incident is None:
            raise SystemExit("No Retriva incident found.")

        payload = {
            "incident_id": str(incident.incident_id),
            "thread_id": incident.thread_id,
            "tenant_id": incident.tenant_id,
            "service": incident.service,
            "status": incident.status,
            "severity": incident.severity,
            "environment": incident.environment,
            "commit_sha": incident.commit_sha,
            "error_class": incident.error_class,
            "error_message": incident.error_message,
            "file_path": incident.file_path,
            "line_number": incident.line_number,
            "analysis_only": incident.analysis_only,
            "trace_id": incident.trace_id,
            "request_id": incident.request_id,
            "dedupe_key": incident.dedupe_key,
            "fix_status": incident.fix_status,
            "fix_error": incident.fix_error,
            "branch_name": incident.branch_name,
            "pr_number": incident.pr_number,
            "pr_url": incident.pr_url,
            "pr_state": incident.pr_state,
            "ci_status": incident.ci_status,
            "model_name": incident.model_name,
            "fix_commit_sha": incident.fix_commit_sha,
            "merged_at": str(incident.merged_at) if incident.merged_at else None,
            "merge_commit_sha": incident.merge_commit_sha,
            "verification_status": incident.verification_status,
            "verification_started_at": (
                str(incident.verification_started_at)
                if incident.verification_started_at
                else None
            ),
            "verification_deadline": (
                str(incident.verification_deadline)
                if incident.verification_deadline
                else None
            ),
            "revert_pr_number": incident.revert_pr_number,
            "revert_pr_url": incident.revert_pr_url,
            "revert_status": incident.revert_status,
            "repository_mapping_id": (
                str(incident.repository_mapping_id)
                if incident.repository_mapping_id
                else None
            ),
        }
        print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
