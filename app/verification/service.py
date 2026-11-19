from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
from sqlalchemy import or_, select

from app.config import settings
from app.revert.service import create_revert_pr
from db.models import Incident, RepositoryMapping
from db.session import SessionLocal
from integrations.github_app import GitHubAppClient
from integrations.notifications import send_gmail_event
from observability.logging import get_logger

log = get_logger(stage="verification")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _fingerprint(record: dict) -> str:
    return "|".join(
        [
            str(record.get("service") or ""),
            str(record.get("error_class") or ""),
            str(record.get("file") or ""),
            str(record.get("line") or 0),
        ]
    )


def _cloudwatch_errors(start: datetime) -> list[dict]:
    session = boto3.Session(
        profile_name=settings.aws_profile or None,
        region_name=settings.aws_region,
    )
    client = session.client("logs")
    start_ms = int(start.timestamp() * 1000)
    events: list[dict] = []
    token: str | None = None
    while True:
        kwargs = {
            "logGroupName": settings.verification_log_group,
            "startTime": start_ms,
            "filterPattern": '{ $.level = "ERROR" }',
            "limit": 1000,
        }
        if token:
            kwargs["nextToken"] = token
        response = client.filter_log_events(**kwargs)
        for item in response.get("events", []):
            try:
                record = json.loads(item.get("message", ""))
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(record, dict):
                events.append(record)
        token = response.get("nextToken")
        if not token:
            break
    return events


def _file_errors(start: datetime) -> list[dict]:
    path = Path(settings.verification_log_file)
    if not path.is_file():
        return []
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        timestamp = _parse_dt(record.get("timestamp"))
        if timestamp and timestamp < start:
            continue
        events.append(record)
    return events


def fetch_errors(start: datetime) -> list[dict]:
    if settings.verification_log_source == "file":
        return _file_errors(start)
    return _cloudwatch_errors(start)


def _client(incident: Incident, mapping: RepositoryMapping) -> GitHubAppClient:
    return GitHubAppClient(
        app_id=settings.github_app_id,
        installation_id=settings.github_installation_id,
        private_key_path=settings.github_app_private_key_path,
        repo=mapping.repo_full_name,
        base_branch=mapping.base_branch,
        api_url=settings.github_api_url,
    )


def verify_incident(incident_id: uuid.UUID, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    with SessionLocal() as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            return {"status": "incident_missing"}
        mapping = (
            session.get(RepositoryMapping, incident.repository_mapping_id)
            if incident.repository_mapping_id
            else None
        )
        if mapping is None:
            return {"status": "repo_mapping_missing"}
        if not incident.pr_number:
            return {"status": "no_pr"}

        client = _client(incident, mapping)
        pr = client.get_pr(incident.pr_number)
        incident.pr_state = pr.get("state")

        if not pr.get("merged"):
            if pr.get("state") == "closed":
                incident.status = "rejected"
                session.commit()
            return {"status": "not_merged"}

        merged_at = _parse_dt(pr.get("merged_at")) or now
        if incident.verification_status is None:
            incident.merged_at = merged_at
            incident.merge_commit_sha = pr.get("merge_commit_sha")
            incident.verification_started_at = merged_at
            incident.verification_deadline = merged_at + timedelta(
                minutes=settings.verification_window_minutes
            )
            incident.verification_status = "pending"
            incident.fix_status = "merged"
            incident.status = "verifying"
            session.commit()
            log.bind(
                incident_id=str(incident.incident_id),
                pr_number=incident.pr_number,
            ).info("PR merged; verification window started")

        if incident.verification_status in {"verified", "regressed", "inconclusive"}:
            return {"status": incident.verification_status}

        start = incident.verification_started_at or merged_at
        try:
            errors = fetch_errors(start)
        except Exception as exc:
            log.bind(error=str(exc)).exception("verification log query failed")
            if now >= (incident.verification_deadline or now):
                incident.verification_status = "inconclusive"
                incident.status = "inconclusive"
                session.commit()
                return {"status": "inconclusive", "error": str(exc)}
            return {"status": "pending", "error": str(exc)}

        match = next(
            (
                record
                for record in errors
                if _fingerprint(record) == (incident.error_fingerprint or "")
            ),
            None,
        )
        if match is not None:
            incident.verification_status = "regressed"
            incident.status = "regressed"
            incident.fix_status = "regressed"
            session.commit()
            revert = create_revert_pr(
                incident.incident_id,
                reason="Original error fingerprint reappeared during verification",
            )
            session.refresh(incident)
            send_gmail_event(
                event="regressed",
                incident=incident,
                pr_url=incident.pr_url,
                revert_pr_url=incident.revert_pr_url,
            )
            return {
                "status": "regressed",
                "incident_id": str(incident_id),
                "revert": revert,
            }

        deadline = incident.verification_deadline or now
        if now >= deadline:
            incident.verification_status = "verified"
            incident.status = "resolved"
            incident.fix_status = "resolved"
            incident.resolved_at = now
            session.commit()
            send_gmail_event(
                event="resolved",
                incident=incident,
                pr_url=incident.pr_url,
            )
            return {"status": "resolved", "incident_id": str(incident_id)}

        return {
            "status": "pending",
            "incident_id": str(incident_id),
            "deadline": incident.verification_deadline.isoformat()
            if incident.verification_deadline
            else None,
        }


def verify_pending() -> list[dict]:
    with SessionLocal() as session:
        incidents = session.execute(
            select(Incident).where(
                Incident.pr_number.is_not(None),
                or_(
                    Incident.verification_status.is_(None),
                    Incident.verification_status.in_(["pending", "verifying"]),
                ),
                Incident.status.notin_(["resolved", "regressed", "rejected"]),
            )
        ).scalars().all()
        ids = [incident.incident_id for incident in incidents]
    return [verify_incident(incident_id) for incident_id in ids]
