# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()  # Automatically loads from `.env` or `.env.local`

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_MESSAGE_TRANSPORT = os.getenv("DEFAULT_MESSAGE_TRANSPORT", "SLIM")
TRANSPORT_SERVER_ENDPOINT = os.getenv("TRANSPORT_SERVER_ENDPOINT", "http://localhost:46357")

LLM_MODEL = os.getenv("LLM_MODEL", "")
## Oauth2 OpenAI Provider
OAUTH2_CLIENT_ID= os.getenv("OAUTH2_CLIENT_ID", "")
OAUTH2_CLIENT_SECRET= os.getenv("OAUTH2_CLIENT_SECRET", "")
OAUTH2_TOKEN_URL= os.getenv("OAUTH2_TOKEN_URL", "")
OAUTH2_BASE_URL= os.getenv("OAUTH2_BASE_URL", "")
OAUTH2_APPKEY= os.getenv("OAUTH2_APPKEY", "")

LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", "INFO").upper()

# Bilateral AML 314(b) runtime configuration
AML314B_REQUESTOR_HOST = os.getenv("AML314B_REQUESTOR_HOST", "127.0.0.1")
AML314B_REQUESTOR_PORT = int(os.getenv("AML314B_REQUESTOR_PORT", "8011"))
AML314B_RESPONDER_HOST = os.getenv("AML314B_RESPONDER_HOST", "127.0.0.1")
AML314B_RESPONDER_PORT = int(os.getenv("AML314B_RESPONDER_PORT", "8012"))

_default_responder_base_url = f"http://{AML314B_RESPONDER_HOST}:{AML314B_RESPONDER_PORT}"
AML314B_RESPONDER_BASE_URL = os.getenv("AML314B_RESPONDER_BASE_URL", _default_responder_base_url)
AML314B_MESSAGE_TRANSPORT = os.getenv("AML314B_MESSAGE_TRANSPORT", "SLIM")
AML314B_TRANSPORT_SERVER_ENDPOINT = os.getenv(
    "AML314B_TRANSPORT_SERVER_ENDPOINT", TRANSPORT_SERVER_ENDPOINT
)
AML314B_ENABLE_TRACING = (
    os.getenv("AML314B_ENABLE_TRACING", "true").lower() == "true"
)

AML314B_ACTIVE_INVESTIGATIONS_PATH = os.getenv(
    "AML314B_ACTIVE_INVESTIGATIONS_PATH",
    str(BASE_DIR / "fi_a" / "data" / "active_investigations.csv"),
)
AML314B_DIRECTORY_PATH = os.getenv(
    "AML314B_DIRECTORY_PATH",
    str(BASE_DIR / "aml314b" / "data" / "counterparty_directory.csv"),
)
AML314B_RETRIEVED_INFORMATION_PATH = os.getenv(
    "AML314B_RETRIEVED_INFORMATION_PATH",
    str(BASE_DIR / "fi_a" / "data" / "retrieved_information.csv"),
)
AML314B_KNOWN_HIGH_RISK_ENTITIES_PATH = os.getenv(
    "AML314B_KNOWN_HIGH_RISK_ENTITIES_PATH",
    str(BASE_DIR / "fi_b" / "data" / "known_high_risk_entities.csv"),
)
AML314B_CURATED_CONTEXT_PATH = os.getenv(
    "AML314B_CURATED_CONTEXT_PATH",
    str(BASE_DIR / "fi_b" / "data" / "curated_investigative_context.csv"),
)
AML314B_INTERNAL_INVESTIGATIONS_PATH = os.getenv(
    "AML314B_INTERNAL_INVESTIGATIONS_PATH",
    str(BASE_DIR / "fi_b" / "data" / "internal_investigations.csv"),
)

AML314B_REQUESTOR_AUTOSTART = os.getenv("AML314B_REQUESTOR_AUTOSTART", "true").lower() == "true"
AML314B_REQUESTOR_CASE_LIMIT = (
    int(os.getenv("AML314B_REQUESTOR_CASE_LIMIT"))
    if os.getenv("AML314B_REQUESTOR_CASE_LIMIT")
    else None
)
AML314B_USE_LLM_RISK_CLASSIFIER = (
    os.getenv("AML314B_USE_LLM_RISK_CLASSIFIER", "false").lower() == "true"
)
AML314B_UI_STEP_DELAY_SECONDS = float(os.getenv("AML314B_UI_STEP_DELAY_SECONDS", "1"))

AML314B_ENABLE_LAYERED_DISCLOSURE = (
    os.getenv("AML314B_ENABLE_LAYERED_DISCLOSURE", "false").lower() == "true"
)
AML314B_DISCLOSURE_AUDIT_PATH = os.getenv(
    "AML314B_DISCLOSURE_AUDIT_PATH",
    str(BASE_DIR / "fi_b" / "data" / "disclosure_audit.csv"),
)
AML314B_DISCLOSURE_POLICY_TEXT = os.getenv(
    "AML314B_DISCLOSURE_POLICY_TEXT",
    (
        "Allow only AML_314B bounded investigative context. "
        "Never disclose SSNs or direct sensitive identifiers. "
        "Do not disclose details that, by themselves or cumulatively for the same requester and entity, "
        "exceed policy-approved 314(b) sharing scope."
    ),
)
AML314B_DISCLOSURE_FAIL_CLOSED = (
    os.getenv("AML314B_DISCLOSURE_FAIL_CLOSED", "true").lower() == "true"
)
AML314B_DEFAULT_REQUESTER_INSTITUTION_ID = os.getenv(
    "AML314B_DEFAULT_REQUESTER_INSTITUTION_ID", "FI-A"
)
AML314B_DEFAULT_RESPONDER_INSTITUTION_ID = os.getenv(
    "AML314B_DEFAULT_RESPONDER_INSTITUTION_ID", "FI-B"
)
