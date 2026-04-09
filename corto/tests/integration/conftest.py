import os
from pathlib import Path

import pytest

from tests.integration.docker_helpers import up, down

files = ["docker-compose.yaml"]
if Path("docker-compose.override.yaml").exists():
    files.append("docker-compose.override.yaml")
 
@pytest.fixture(scope="session", autouse=True)
def orchestrate_session_services():
    if os.getenv("SKIP_SESSION_SERVICES", "").lower() == "true":
        print("\n--- SKIP_SESSION_SERVICES=true; skipping docker-compose session services ---")
        yield
        return
    print("\n--- Setting up AML session services ---")
    _startup_slim()
    print("--- AML session service setup complete. Tests can now run ---")
    yield
    down(files)

def _startup_slim():
    up(files, ["slim"])
