from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import jwt

from app.config import settings


class GitHubAppError(RuntimeError):
    pass


@dataclass
class PullRequestInfo:
    number: int
    url: str
    state: str
    draft: bool
    head_sha: str
    base_branch: str


class GitHubAppClient:
    def __init__(
        self,
        *,
        app_id: int,
        installation_id: int,
        private_key_path: str,
        repo: str,
        base_branch: str = "main",
        api_url: str = "https://api.github.com",
    ) -> None:
        if not app_id or not installation_id:
            raise GitHubAppError("GitHub App ID and installation ID are required")
        key_path = Path(private_key_path)
        if not key_path.is_file():
            raise GitHubAppError(f"GitHub App private key not found: {key_path}")
        self.app_id = app_id
        self.installation_id = installation_id
        self.private_key = key_path.read_text(encoding="utf-8")
        self.repo = repo
        self.base_branch = base_branch
        self.api_url = api_url.rstrip("/")
        self._token: str | None = None
        self._token_expires_at = 0.0

    def _app_jwt(self) -> str:
        now = int(time.time())
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": str(self.app_id)},
            self.private_key,
            algorithm="RS256",
        )

    def installation_token(self, *, force: bool = False) -> str:
        if self._token and not force and time.time() < self._token_expires_at:
            return self._token

        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{self.api_url}/app/installations/{self.installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {self._app_jwt()}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        if response.status_code != 201:
            raise GitHubAppError(
                f"installation token failed ({response.status_code}): {response.text[:300]}"
            )
        data = response.json()
        self._token = data["token"]
        self._token_expires_at = time.time() + 55 * 60
        return self._token

    def _request(
        self,
        method: str,
        path: str,
        *,
        retry_auth: bool = True,
        **kwargs: Any,
    ) -> Any:
        headers = {
            "Authorization": f"Bearer {self.installation_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        headers.update(kwargs.pop("headers", {}))
        last_error: Exception | None = None
        response: httpx.Response | None = None
        for attempt in range(max(1, settings.github_retry_attempts)):
            try:
                with httpx.Client(timeout=30) as client:
                    response = client.request(
                        method,
                        f"{self.api_url}/repos/{self.repo}{path}",
                        headers=headers,
                        **kwargs,
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = GitHubAppError(
                        f"GitHub API {method} {path} returned {response.status_code}"
                    )
                    time.sleep(min(2**attempt, 8))
                    continue
                break
            except (httpx.HTTPError, OSError) as exc:
                last_error = exc
                time.sleep(min(2**attempt, 8))
        if response is None:
            raise GitHubAppError(f"GitHub API {method} {path} failed: {last_error}")
        if response.status_code in {401, 403} and retry_auth:
            self.installation_token(force=True)
            return self._request(
                method, path, retry_auth=False, headers=kwargs.pop("headers", {}), **kwargs
            )
        if response.status_code >= 400:
            raise GitHubAppError(
                f"GitHub API {method} {path} failed ({response.status_code}): "
                f"{response.text[:500]}"
            )
        if response.status_code == 204:
            return None
        return response.json()

    def get_commit(self, sha: str) -> dict[str, Any]:
        return self._request("GET", f"/commits/{sha}")

    def get_branch_sha(self, branch: str) -> str:
        data = self._request("GET", f"/branches/{quote(branch, safe='')}")
        return data["commit"]["sha"]

    def get_file_at_sha(self, path: str, sha: str) -> tuple[str, str]:
        data = self._request(
            "GET",
            f"/contents/{path}",
            params={"ref": sha},
        )
        if data.get("encoding") != "base64":
            raise GitHubAppError(f"unexpected content encoding for {path}")
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]

    def create_blob(self, content: str) -> str:
        data = self._request(
            "POST",
            "/git/blobs",
            json={"content": content, "encoding": "utf-8"},
        )
        return data["sha"]

    def create_tree(self, base_tree_sha: str, path: str, blob_sha: str) -> str:
        data = self._request(
            "POST",
            "/git/trees",
            json={
                "base_tree": base_tree_sha,
                "tree": [
                    {
                        "path": path,
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob_sha,
                    }
                ],
            },
        )
        return data["sha"]

    def create_commit(
        self, *, message: str, tree_sha: str, parent_sha: str
    ) -> str:
        data = self._request(
            "POST",
            "/git/commits",
            json={"message": message, "tree": tree_sha, "parents": [parent_sha]},
        )
        return data["sha"]

    def create_branch(self, *, branch: str, sha: str) -> None:
        self._request(
            "POST",
            "/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )

    def open_draft_pr(
        self,
        *,
        title: str,
        body: str,
        head: str,
        base: str | None = None,
    ) -> PullRequestInfo:
        data = self._request(
            "POST",
            "/pulls",
            json={
                "title": title,
                "body": body,
                "head": head,
                "base": base or self.base_branch,
                "draft": True,
                "maintainer_can_modify": True,
            },
        )
        return PullRequestInfo(
            number=data["number"],
            url=data["html_url"],
            state=data["state"],
            draft=bool(data.get("draft")),
            head_sha=data["head"]["sha"],
            base_branch=data["base"]["ref"],
        )

    def get_pr(self, number: int) -> dict[str, Any]:
        return self._request("GET", f"/pulls/{number}")

    def update_pr_body(self, number: int, body: str) -> dict[str, Any]:
        return self._request("PATCH", f"/pulls/{number}", json={"body": body})

    def list_check_runs(self, ref: str) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            f"/commits/{ref}/check-runs",
            params={"per_page": 100},
        )
        return data.get("check_runs", [])

    def wait_for_required_checks(
        self,
        *,
        ref: str,
        required: tuple[str, ...] = ("test", "lint"),
        timeout_seconds: int = 300,
        interval_seconds: int = 10,
    ) -> dict[str, Any]:
        deadline = time.time() + timeout_seconds
        latest: dict[str, dict[str, Any]] = {}
        while True:
            runs = self.list_check_runs(ref)
            latest = {
                run["name"]: {
                    "status": run.get("status"),
                    "conclusion": run.get("conclusion"),
                    "details_url": run.get("details_url"),
                }
                for run in runs
            }
            required_runs = [latest.get(name) for name in required]
            if all(
                run and run.get("status") == "completed" for run in required_runs
            ):
                failed = [
                    name
                    for name, run in zip(required, required_runs)
                    if run.get("conclusion") != "success"
                ]
                return {
                    "status": "failed" if failed else "passed",
                    "required": list(required),
                    "checks": latest,
                    "failed": failed,
                }
            if time.time() >= deadline:
                return {
                    "status": "pending",
                    "required": list(required),
                    "checks": latest,
                    "failed": [],
                }
            time.sleep(interval_seconds)
