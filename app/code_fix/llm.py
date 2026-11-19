from __future__ import annotations

import difflib
import json
import re
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.config import settings
from app.code_fix.context import CodeContext
from observability.logging import get_logger

log = get_logger(stage="code_fix.llm")

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class PatchGenerationError(RuntimeError):
    pass


class CodePatch(BaseModel):
    file_path: str
    unified_diff: str = ""
    search: str = ""
    replace: str = ""
    explanation: str
    test_plan: list[str] = Field(default_factory=list)


def _system_prompt() -> str:
    return """You are a senior Python engineer fixing one production error.

Return ONLY valid JSON with this exact shape:
{
  "file_path": "relative/path.py",
  "search": "exact existing code lines copied from the file",
  "replace": "replacement code lines",
  "explanation": "short root-cause and fix explanation",
  "test_plan": ["..."],
}

Rules:
- Make the smallest safe change that fixes the reported error.
- `search` MUST be copied exactly from the file and occur exactly once.
- Do not include line-number prefixes in `search` or `replace`.
- Do not change CI workflows, secrets, auth, migrations, dependencies, or unrelated files.
- Do not wrap the JSON in Markdown fences.
- Return the exact failing line or a small surrounding block, not a whole function.
"""


def _user_prompt(context: CodeContext, error: dict[str, Any]) -> str:
    lines = context.content.splitlines()
    target = lines[context.line - 1] if 0 < context.line <= len(lines) else ""
    return f"""Repository file: {context.file_path}
Error line: {context.line}
Error class: {error.get('error_class')}
Error message: {error.get('message')}
Environment: {error.get('environment')}
Commit: {error.get('commit_sha')}

<target_line>
{target}
</target_line>

<stack_trace>
{str(error.get('stack_trace') or '')[:4000]}
</stack_trace>

<file_context>
{context.snippet}
</file_context>

Return a search/replace fix for the target line. `search` must be exact file
text without the displayed line-number prefix.
"""


def _parse_content(content: str) -> CodePatch:
    text = _FENCE.sub("", content.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PatchGenerationError(f"model returned invalid JSON: {exc}") from exc
    if "diff" in data and "unified_diff" not in data:
        data["unified_diff"] = data["diff"]
    return CodePatch.model_validate(data)


def _build_diff(context: CodeContext, patch: CodePatch) -> CodePatch:
    if patch.unified_diff.strip():
        return patch
    search = patch.search
    replace = patch.replace
    if not search or not replace:
        raise PatchGenerationError("model returned neither a diff nor search/replace")
    count = context.content.count(search)
    if count != 1:
        raise PatchGenerationError(
            f"search text must occur exactly once in {context.file_path}; got {count}"
        )
    updated = context.content.replace(search, replace, 1)
    diff = "".join(
        difflib.unified_diff(
            context.content.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{context.file_path}",
            tofile=f"b/{context.file_path}",
            n=3,
        )
    )
    if not diff:
        raise PatchGenerationError("search/replace produced no diff")
    return patch.model_copy(update={"unified_diff": diff})


def generate_patch(context: CodeContext, error: dict[str, Any]) -> CodePatch:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    last_error = ""

    for attempt in range(1, max(1, settings.ollama_retry_attempts) + 1):
        messages = [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": _user_prompt(context, error)},
        ]
        if last_error:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous answer was invalid: "
                        f"{last_error}. Return only the required JSON."
                    ),
                }
            )

        try:
            response = httpx.post(
                url,
                json={
                    "model": settings.ollama_code_model,
                    "messages": messages,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0,
                        "num_ctx": 8192,
                        "num_predict": 1200,
                    },
                },
                timeout=settings.ollama_code_timeout_seconds,
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]
            patch = _parse_content(content)
            patch = _build_diff(context, patch)
            if not patch.unified_diff.strip():
                raise PatchGenerationError("model returned an empty diff")
            log.bind(
                model=settings.ollama_code_model,
                attempt=attempt,
                file_path=patch.file_path,
            ).info("patch generated")
            return patch
        except Exception as exc:
            last_error = str(exc)
            log.bind(
                model=settings.ollama_code_model,
                attempt=attempt,
                error=last_error,
            ).warning("patch generation attempt failed")
            if attempt < settings.ollama_retry_attempts:
                time.sleep(min(2**attempt, 8))

    raise PatchGenerationError(
        f"unable to generate a valid patch after "
        f"{settings.ollama_retry_attempts} attempts: {last_error}"
    )
