from __future__ import annotations

import os
import socket
import time
from pathlib import Path

import httpx
import pytest

from tests.integration.process_helper import ProcessRunner


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.skipif(os.getenv("SKIP_A2A_HTTP_TEST") == "true", reason="A2A HTTP test disabled")
def test_aml314b_a2a_http_roundtrip(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    requestor_port = _find_free_port()
    responder_port = _find_free_port()
    directory_path = tmp_path / "counterparty_directory.csv"
    directory_path.write_text(
        "institution_id,transport,endpoint,enabled\n"
        f"FI-B,A2A,http://127.0.0.1:{responder_port},true\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "AML314B_MESSAGE_TRANSPORT": "A2A",
            "AML314B_REQUESTOR_AUTOSTART": "false",
            "AML314B_REQUESTOR_CASE_LIMIT": "1",
            "AML314B_REQUESTOR_PORT": str(requestor_port),
            "AML314B_RESPONDER_PORT": str(responder_port),
            "AML314B_ENABLE_TRACING": "false",
            "AML314B_ENABLE_LAYERED_DISCLOSURE": "false",
            "AML314B_USE_LLM_RISK_CLASSIFIER": "false",
            "AML314B_RETRIEVED_INFORMATION_PATH": str(tmp_path / "retrieved_information.csv"),
            "AML314B_INTERNAL_INVESTIGATIONS_PATH": str(
                tmp_path / "internal_investigations.csv"
            ),
            "AML314B_DIRECTORY_PATH": str(directory_path),
        }
    )

    fi_b = ProcessRunner(
        name="aml-fi-b-a2a",
        cmd=["uv", "run", "python", "fi_b/a2a_server.py"],
        cwd=str(repo_root),
        env=env,
        ready_pattern=r"Uvicorn running on",
        timeout_s=40,
    ).start()
    fi_b.wait_ready()

    fi_a = ProcessRunner(
        name="aml-fi-a",
        cmd=["uv", "run", "python", "fi_a/main.py"],
        cwd=str(repo_root),
        env=env,
        ready_pattern=r"Uvicorn running on",
        timeout_s=40,
    ).start()
    fi_a.wait_ready()

    try:
        time.sleep(1.0)
        response = httpx.post(
            f"http://127.0.0.1:{requestor_port}/aml314b/run/CASE-JOHN-01", timeout=30.0
        )
        response.raise_for_status()
        payload = response.json()
        assert payload["status"] == "success"
        assert payload["match_type"] == "CONFIRMED_MATCH"

        retrieved = httpx.get(
            f"http://127.0.0.1:{requestor_port}/aml314b/retrieved",
            timeout=30.0,
        )
        retrieved.raise_for_status()
        rows = retrieved.json()
        assert any(row["case_id"] == "CASE-JOHN-01" for row in rows)
    finally:
        fi_a.stop()
        fi_b.stop()
