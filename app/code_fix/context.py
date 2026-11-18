from __future__ import annotations

from dataclasses import dataclass

from integrations.github_app import GitHubAppClient


@dataclass
class CodeContext:
    file_path: str
    content: str
    blob_sha: str
    line: int
    start_line: int
    end_line: int
    snippet: str


def fetch_code_context(
    client: GitHubAppClient,
    *,
    commit_sha: str,
    file_path: str,
    line: int,
    window: int = 80,
) -> CodeContext:
    content, blob_sha = client.get_file_at_sha(file_path, commit_sha)
    lines = content.splitlines()
    target = max(1, min(line or 1, len(lines))) if lines else 1
    start = max(1, target - window)
    end = min(len(lines), target + window)
    snippet = "\n".join(
        f"{number:>4}: {lines[number - 1]}"
        for number in range(start, end + 1)
    )
    return CodeContext(
        file_path=file_path,
        content=content,
        blob_sha=blob_sha,
        line=target,
        start_line=start,
        end_line=end,
        snippet=snippet,
    )
