from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "private_key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
        "***REDACTED_PRIVATE_KEY***",
    ),
    (
        "aws_access_key",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        "***REDACTED_AWS_KEY***",
    ),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"),
        "***REDACTED_JWT***",
    ),
    (
        "bearer_token",
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
        "Bearer ***REDACTED***",
    ),
    (
        "secret_assignment",
        re.compile(
            r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|auth[_-]?token)"
            r"\b(\s*[:=]\s*)[\"']?([^\s\"',;]+)"
        ),
        r"\1\2***REDACTED***",
    ),
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
        "***REDACTED_EMAIL***",
    ),
]

def redact(text: str) -> tuple[str, dict[str, int]]:

    counts: dict[str, int] = {}
    out = text
    for name, pattern, replacement in _PATTERNS:
        out, n = pattern.subn(replacement, out)
        if n:
            counts[name] = n
    return out, counts
