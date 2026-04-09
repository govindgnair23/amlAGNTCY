from __future__ import annotations

import json
import logging

from dotenv import load_dotenv

from aml314b.bilateral import run_bilateral_demo_sync
from config.logging_config import setup_logging

load_dotenv()
setup_logging()
logger = logging.getLogger("corto.aml314b.demo")


def main() -> None:
    outcome = run_bilateral_demo_sync()
    logger.info("AML314B bilateral demo processed cases=%s", outcome["cases_processed"])
    logger.info("AML314B bilateral demo results=%s", json.dumps(outcome["results"], indent=2))
    logger.info("Retrieved information path: %s", outcome["retrieved_information_path"])
    logger.info("Internal investigations path: %s", outcome["internal_investigations_path"])


if __name__ == "__main__":
    main()
