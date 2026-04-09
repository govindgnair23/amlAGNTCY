import sys
from pathlib import Path

if __package__ in {None, ""}:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").exists():
            sys.path.insert(0, str(candidate))
            break

from aml314b.institutions.common.runtime import run_responder_sync
from aml314b.institutions.fi_b.card import AGENT_CARD
from config.config import AML314B_DISCOVERY_RESPONDER_BASE_PORT


if __name__ == "__main__":
    run_responder_sync(
        app_name="lungo.aml314b.fi_b",
        institution_id="FI_B",
        agent_card=AGENT_CARD,
        data_dir=Path(__file__).resolve().parent / "data",
        port=AML314B_DISCOVERY_RESPONDER_BASE_PORT,
    )
