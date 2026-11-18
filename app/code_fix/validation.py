from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.code_fix.context import CodeContext
from app.code_fix.llm import CodePatch
from app.config import settings


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    patched_content: str = ""
    added_lines: int = 0
    removed_lines: int = 0


_SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(password|secret|api[_-]?key|auth[_-]?token)\s*=\s*['\"][^'\"]+"),
)


def _run(
    args: list[str], *, cwd: Path, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )


def _diff_counts(diff: str) -> tuple[int, int]:
    added = 0
    removed = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def _secret_errors(diff: str) -> list[str]:
    errors: list[str] = []
    for line in diff.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for pattern in _SECRET_PATTERNS:
            if pattern.search(line):
                errors.append("patch appears to contain a secret")
                return errors
    return errors


def _find_ruff(repo_root: Path) -> list[str] | None:
    if sys.platform == "win32":
        target_python = repo_root / ".venv" / "Scripts" / "python.exe"
    else:
        target_python = repo_root / ".venv" / "bin" / "python"
    if target_python.is_file():
        return [str(target_python), "-m", "ruff"]
    ruff = shutil.which("ruff")
    return [ruff] if ruff else None


def validate_patch(
    context: CodeContext,
    patch: CodePatch,
    *,
    repo_root: Path,
) -> ValidationResult:
    errors: list[str] = []
    path = patch.file_path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    if path != context.file_path:
        errors.append(
            f"patch targets {path!r}, expected {context.file_path!r}"
        )
    if Path(path).is_absolute() or ".." in Path(path).parts:
        errors.append("patch path escapes the repository")

    denied = [
        item.strip()
        for item in settings.github_denied_paths.split(",")
        if item.strip()
    ]
    if any(path.startswith(item) for item in denied):
        errors.append(f"path is denied by policy: {path}")

    added, removed = _diff_counts(patch.unified_diff)
    if added + removed > settings.github_max_diff_lines:
        errors.append(
            f"diff exceeds {settings.github_max_diff_lines} changed lines "
            f"(got {added + removed})"
        )
    if added + removed == 0:
        errors.append("diff has no changed lines")
    errors.extend(_secret_errors(patch.unified_diff))

    if errors:
        return ValidationResult(
            ok=False,
            errors=errors,
            added_lines=added,
            removed_lines=removed,
        )

    workdir = Path(tempfile.mkdtemp(prefix="opsflow-patch-"))
    try:
        target = workdir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(context.content, encoding="utf-8")
        diff_file = workdir / "patch.diff"
        diff_file.write_text(patch.unified_diff.rstrip() + "\n", encoding="utf-8")

        commands = [
            ["git", "init", "-q"],
            ["git", "config", "user.email", "opsflow@local"],
            ["git", "config", "user.name", "OpsFlow"],
            ["git", "add", "."],
            ["git", "commit", "-q", "-m", "base"],
            ["git", "apply", "--check", "patch.diff"],
            ["git", "apply", "patch.diff"],
        ]
        for command in commands:
            result = _run(command, cwd=workdir)
            if result.returncode != 0:
                errors.append(
                    f"{' '.join(command)} failed: "
                    f"{(result.stderr or result.stdout).strip()[:1000]}"
                )
                return ValidationResult(
                    ok=False,
                    errors=errors,
                    added_lines=added,
                    removed_lines=removed,
                )

        patched = target.read_text(encoding="utf-8")
        compile_result = _run(
            [sys.executable, "-m", "py_compile", str(target)],
            cwd=workdir,
        )
        if compile_result.returncode != 0:
            errors.append(
                "patched file failed py_compile: "
                f"{(compile_result.stderr or compile_result.stdout).strip()[:1000]}"
            )

        ruff = _find_ruff(repo_root)
        if ruff:
            ruff_command = [*ruff, "check", str(target)]
            pyproject = repo_root / "pyproject.toml"
            if pyproject.is_file():
                ruff_command.extend(["--config", str(pyproject)])
            ruff_result = _run(ruff_command, cwd=repo_root)
            if ruff_result.returncode != 0:
                errors.append(
                    "patched file failed ruff: "
                    f"{(ruff_result.stdout or ruff_result.stderr).strip()[:1000]}"
                )

        return ValidationResult(
            ok=not errors,
            errors=errors,
            patched_content=patched,
            added_lines=added,
            removed_lines=removed,
        )
    except Exception as exc:
        errors.append(f"validation crashed: {exc}")
        return ValidationResult(
            ok=False,
            errors=errors,
            added_lines=added,
            removed_lines=removed,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
