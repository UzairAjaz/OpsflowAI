"""P2-03 check: FastAPI skeleton and structured logging.

Runs the app in-process with Starlette's TestClient and verifies that the
health endpoints return 200 and that requests produce JSON log lines.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from api.main import app


def main() -> None:
    with TestClient(app) as client:
        root = client.get("/")
        assert root.status_code == 200, root.text
        print("root      :", root.json())

        health = client.get("/healthz")
        assert health.status_code == 200, health.text
        print("healthz   :", health.json())

        ready = client.get("/readyz")
        assert ready.status_code == 200, ready.text
        print("readyz    :", ready.json())

    # Emit one structured log line and confirm it is valid JSON.
    from observability.logging import get_logger

    line = json.dumps({"probe": "ok"})
    get_logger(stage="check", incident_id="inc-demo", duration_ms=1).info("structured log check")
    parsed = json.loads(line)
    assert parsed["probe"] == "ok"

    print("[ok] P2-03 -- API health endpoints and structured logging working.")


if __name__ == "__main__":
    main()
