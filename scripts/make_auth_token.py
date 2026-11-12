from __future__ import annotations

import argparse

from api.auth import ROLES, create_access_token


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an OpsFlow JWT access token")
    parser.add_argument("--tenant", default="mediconnect")
    parser.add_argument("--subject", default="demo-user")
    parser.add_argument("--role", default="approver", choices=list(ROLES))
    parser.add_argument("--ttl-minutes", type=int, default=None)
    args = parser.parse_args()

    token = create_access_token(
        tenant_id=args.tenant,
        subject=args.subject,
        role=args.role,
        ttl_minutes=args.ttl_minutes,
    )
    print(token)


if __name__ == "__main__":
    main()
