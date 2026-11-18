from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from app.code_fix.context import fetch_code_context
from app.code_fix.llm import generate_patch
from app.code_fix.validation import validate_patch
from app.config import settings
from db.models import AuditLog, Incident, RepositoryMapping, Tenant
from db.session import SessionLocal
from integrations.github_app import GitHubAppClient
from observability.logging import get_logger

log = get_logger(stage="code_fix.runner")


def _mapping_for(session, incident: Incident) -> RepositoryMapping | None:
    if incident.repository_mapping_id:
        mapping = session.get(RepositoryMapping, incident.repository_mapping_id)
        if mapping is not None:
            return mapping
    return None


def _pr_body(incident: Incident, patch, validation, check_summary) -> str:
    return f"""## OpsFlow AI Draft Fix

**Incident:** `{incident.thread_id}`  
**Service:** `{incident.service}`  
**Environment:** `{incident.environment or 'unknown'}`  
**Commit:** `{incident.commit_sha or 'unknown'}`  
**Error:** `{incident.error_class or 'unknown'}` at `{incident.file_path}:{incident.line_number}`

### Explanation

{patch.explanation}

### Validation

- Added lines: {validation.added_lines}
- Removed lines: {validation.removed_lines}
- `git apply --check`: passed
- Python compile: passed
- Ruff: passed
- Secret scan: passed

### CI

```text
{json.dumps(check_summary, indent=2)}
```

### Review

AI-generated change. Human review is required. Do not auto-merge.
"""


def _audit(session, incident: Incident, action: str, details: dict) -> None:
    if session.get(Tenant, incident.tenant_id) is None:
        return
    session.add(
        AuditLog(
            tenant_id=incident.tenant_id,
            incident_id=incident.incident_id,
            action=action,
            actor="agent",
            details=details,
        )
    )


def run_code_fix(incident_id: uuid.UUID, *, force: bool = False) -> dict:
    with SessionLocal() as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            raise SystemExit(f"Incident not found: {incident_id}")

        mapping = _mapping_for(session, incident)
        if mapping is None:
            incident.fix_status = "repo_mapping_missing"
            incident.fix_error = "No repository mapping for incident"
            session.commit()
            return {"status": "repo_mapping_missing", "incident_id": str(incident_id)}

        if not force and (
            not settings.code_fix_enabled
            or settings.code_fix_analysis_only
            or incident.analysis_only
        ):
            incident.fix_status = "disabled"
            incident.fix_error = "Code fix is disabled or incident is analysis-only"
            session.commit()
            return {"status": "disabled", "incident_id": str(incident_id)}

        if not mapping.local_repo_root:
            incident.fix_status = "repo_root_missing"
            incident.fix_error = "Repository mapping has no local_repo_root"
            session.commit()
            return {"status": "repo_root_missing", "incident_id": str(incident_id)}

        if not incident.commit_sha:
            incident.fix_status = "commit_sha_missing"
            incident.fix_error = "Incident has no commit_sha"
            session.commit()
            return {"status": "commit_sha_missing", "incident_id": str(incident_id)}

        incident.fix_status = "generating"
        incident.fix_error = None
        session.commit()

        try:
            client = GitHubAppClient(
                app_id=settings.github_app_id,
                installation_id=settings.github_installation_id,
                private_key_path=settings.github_app_private_key_path,
                repo=mapping.repo_full_name,
                base_branch=mapping.base_branch,
                api_url=settings.github_api_url,
            )
            context = fetch_code_context(
                client,
                commit_sha=incident.commit_sha,
                file_path=incident.file_path or "",
                line=incident.line_number or 0,
            )
            patch = generate_patch(
                context,
                {
                    "error_class": incident.error_class,
                    "message": incident.error_message or "",
                    "environment": incident.environment,
                    "commit_sha": incident.commit_sha,
                    "stack_trace": incident.stack_trace or "",
                },
            )
            incident.patch_diff = patch.unified_diff
            incident.model_name = settings.ollama_code_model
            incident.fix_status = "patch_generated"
            session.commit()

            validation = validate_patch(
                context,
                patch,
                repo_root=Path(mapping.local_repo_root),
            )
            if not validation.ok:
                incident.fix_status = "patch_invalid"
                incident.fix_error = "; ".join(validation.errors)
                _audit(
                    session,
                    incident,
                    "code_fix.patch_invalid",
                    {"errors": validation.errors},
                )
                session.commit()
                return {
                    "status": "patch_invalid",
                    "incident_id": str(incident_id),
                    "errors": validation.errors,
                }

            base_commit = client.get_commit(incident.commit_sha)
            base_sha = base_commit["sha"]
            base_tree_sha = base_commit["commit"]["tree"]["sha"]
            blob_sha = client.create_blob(validation.patched_content)
            tree_sha = client.create_tree(
                base_tree_sha,
                context.file_path,
                blob_sha,
            )
            branch = f"opsflow/fix-{incident.thread_id.replace('inc-', '')}"
            commit_message = (
                f"fix: resolve {incident.error_class or 'error'} in "
                f"{context.file_path}\n\n"
                f"OpsFlow incident: {incident.thread_id}"
            )
            fix_commit_sha = client.create_commit(
                message=commit_message,
                tree_sha=tree_sha,
                parent_sha=base_sha,
            )
            client.create_branch(branch=branch, sha=fix_commit_sha)
            pr = client.open_draft_pr(
                title=f"fix: {incident.error_class or 'error'} in {context.file_path}",
                body=_pr_body(incident, patch, validation, {"status": "pending"}),
                head=branch,
                base=mapping.base_branch,
            )
            incident.branch_name = branch
            incident.pr_number = pr.number
            incident.pr_url = pr.url
            incident.pr_state = pr.state
            incident.fix_status = "pr_opened"
            incident.ci_status = "pending"
            _audit(
                session,
                incident,
                "code_fix.pr_opened",
                {
                    "branch": branch,
                    "pr_number": pr.number,
                    "pr_url": pr.url,
                    "commit_sha": fix_commit_sha,
                },
            )
            session.commit()

            checks = client.wait_for_required_checks(
                ref=fix_commit_sha,
                required=("test", "lint"),
                timeout_seconds=300,
            )
            incident.ci_status = checks["status"]
            incident.fix_status = f"ci_{checks['status']}"
            if checks["status"] == "passed":
                incident.status = "awaiting_review"
            elif checks["status"] == "failed":
                incident.status = "ci_failed"
            pr_state = client.get_pr(pr.number)
            incident.pr_state = pr_state.get("state")
            client.update_pr_body(
                pr.number,
                _pr_body(incident, patch, validation, checks),
            )
            _audit(
                session,
                incident,
                f"code_fix.ci_{checks['status']}",
                checks,
            )
            session.commit()
            return {
                "status": incident.fix_status,
                "incident_id": str(incident_id),
                "pr_number": pr.number,
                "pr_url": pr.url,
                "branch": branch,
                "commit_sha": fix_commit_sha,
                "ci": checks,
            }
        except Exception as exc:
            incident.fix_status = "fix_failed"
            incident.fix_error = str(exc)[:4000]
            _audit(session, incident, "code_fix.failed", {"error": str(exc)[:2000]})
            session.commit()
            log.bind(incident_id=str(incident_id), error=str(exc)).exception(
                "code fix failed"
            )
            return {
                "status": "fix_failed",
                "incident_id": str(incident_id),
                "error": str(exc),
            }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local OpsFlow code fix")
    parser.add_argument("incident_id", help="Incident UUID")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even if the incident was marked analysis-only",
    )
    args = parser.parse_args()
    result = run_code_fix(uuid.UUID(args.incident_id), force=args.force)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
