from __future__ import annotations

import uuid

from app.config import settings
from db.models import Incident, RepositoryMapping
from db.session import SessionLocal
from integrations.github_app import GitHubAppClient
from observability.logging import get_logger

log = get_logger(stage="revert")


def _mapping(session, incident: Incident) -> RepositoryMapping | None:
    if not incident.repository_mapping_id:
        return None
    return session.get(RepositoryMapping, incident.repository_mapping_id)


def _body(incident: Incident, reason: str) -> str:
    original = incident.pr_url or "(unknown)"
    return f"""## OpsFlow AI Draft Revert

This Draft PR reverts the fix for incident `{incident.thread_id}`.

- **Reason:** {reason}
- **Service:** `{incident.service}`
- **Original fix PR:** {original}
- **Original error:** `{incident.error_class or 'unknown'}` at `{incident.file_path}:{incident.line_number}`
- **AI model:** `{incident.model_name or settings.ollama_code_model}`
- **Cost:** `$0.00`

The revert restores `{incident.file_path}` to the state before the fix.

**Human review is required. This Draft PR must not be auto-merged.**
"""


def create_revert_pr(incident_id: uuid.UUID, *, reason: str) -> dict:
    with SessionLocal() as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            return {"status": "incident_missing"}
        if incident.revert_pr_url:
            return {
                "status": "exists",
                "revert_pr_number": incident.revert_pr_number,
                "revert_pr_url": incident.revert_pr_url,
            }
        if not incident.file_path or not incident.commit_sha or not incident.branch_name:
            return {"status": "missing_context"}

        mapping = _mapping(session, incident)
        if mapping is None:
            return {"status": "repo_mapping_missing"}

        client = GitHubAppClient(
            app_id=settings.github_app_id,
            installation_id=settings.github_installation_id,
            private_key_path=settings.github_app_private_key_path,
            repo=mapping.repo_full_name,
            base_branch=mapping.base_branch,
            api_url=settings.github_api_url,
        )

        merged = bool(incident.merged_at or incident.merge_commit_sha)
        base_branch = mapping.base_branch if merged else incident.branch_name
        base_sha = client.get_branch_sha(base_branch)
        base_commit = client.get_commit(base_sha)
        base_tree_sha = base_commit["commit"]["tree"]["sha"]

        original_content, _ = client.get_file_at_sha(
            incident.file_path,
            incident.commit_sha,
        )
        blob_sha = client.create_blob(original_content)
        tree_sha = client.create_tree(
            base_tree_sha,
            incident.file_path,
            blob_sha,
        )
        revert_branch = f"opsflow/revert-{incident.thread_id.replace('inc-', '')}"
        commit_sha = client.create_commit(
            message=(
                f"revert: undo OpsFlow fix for {incident.thread_id}\n\n"
                f"Reason: {reason}"
            ),
            tree_sha=tree_sha,
            parent_sha=base_sha,
        )
        client.create_branch(branch=revert_branch, sha=commit_sha)
        pr = client.open_draft_pr(
            title=f"revert: OpsFlow fix for {incident.thread_id}",
            body=_body(incident, reason),
            head=revert_branch,
            base=base_branch,
        )

        incident.revert_pr_number = pr.number
        incident.revert_pr_url = pr.url
        incident.revert_status = "draft"
        session.commit()
        log.bind(
            incident_id=str(incident.incident_id),
            revert_pr=pr.number,
            reason=reason,
        ).info("Draft revert PR created")
        return {
            "status": "created",
            "revert_pr_number": pr.number,
            "revert_pr_url": pr.url,
            "revert_branch": revert_branch,
            "base_branch": base_branch,
        }
