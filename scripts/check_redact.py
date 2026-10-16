from __future__ import annotations

from app.safety.redact import redact

SAMPLE = """\
2026-10-04 ERROR db connection failed host=10.0.0.5 user=admin@corp.com
password=Sup3rS3cret! db_password: hunter2
Authorization: Bearer abc123DEF456ghi789xyz
AWS key AKIAIOSFODNN7EXAMPLE leaked in config
token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c
-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA1234567890abcdef
-----END RSA PRIVATE KEY-----
"""

def main() -> None:
    clean, counts = redact(SAMPLE)

    print("=== counts ===")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print(f"  TOTAL: {sum(counts.values())}")

    print("\n=== redacted text ===")
    print(clean)

    for secret in (
        "Sup3rS3cret!",
        "hunter2",
        "abc123DEF456ghi789xyz",
        "AKIAIOSFODNN7EXAMPLE",
        "admin@corp.com",
    ):
        assert secret not in clean, f"Leak! {secret} still present"
    assert "BEGIN RSA PRIVATE KEY" not in clean
    assert "MIIEowIBAAKCAQEA" not in clean
    print("[ok] Step 8 -- no secrets leaked.")

if __name__ == "__main__":
    main()
