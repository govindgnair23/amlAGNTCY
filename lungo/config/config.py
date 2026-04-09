# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

import os
from dotenv import load_dotenv

load_dotenv()  # Automatically loads from `.env` or `.env.local`

DEFAULT_MESSAGE_TRANSPORT = os.getenv("DEFAULT_MESSAGE_TRANSPORT", "NATS")
TRANSPORT_SERVER_ENDPOINT = os.getenv("TRANSPORT_SERVER_ENDPOINT", "nats://localhost:4222")

LLM_MODEL = os.getenv("LLM_MODEL", "")
## Oauth2 OpenAI Provider
OAUTH2_CLIENT_ID= os.getenv("OAUTH2_CLIENT_ID", "")
OAUTH2_CLIENT_SECRET= os.getenv("OAUTH2_CLIENT_SECRET", "")
OAUTH2_TOKEN_URL= os.getenv("OAUTH2_TOKEN_URL", "")
OAUTH2_BASE_URL= os.getenv("OAUTH2_BASE_URL", "")
OAUTH2_APPKEY= os.getenv("OAUTH2_APPKEY", "")

LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", "INFO").upper()

ENABLE_HTTP = os.getenv("ENABLE_HTTP", "true").lower() in ("true", "1", "yes")

AML314B_DISCOVERY_REQUESTOR_HOST = os.getenv("AML314B_DISCOVERY_REQUESTOR_HOST", "127.0.0.1")
AML314B_DISCOVERY_REQUESTOR_PORT = int(os.getenv("AML314B_DISCOVERY_REQUESTOR_PORT", "9110"))
AML314B_DISCOVERY_RESPONDER_BASE_PORT = int(
    os.getenv("AML314B_DISCOVERY_RESPONDER_BASE_PORT", "9120")
)
AML314B_RESPONDER_HOST = os.getenv("AML314B_RESPONDER_HOST", "127.0.0.1")
AML314B_DIRECTORY_PATH = os.getenv(
    "AML314B_DIRECTORY_PATH",
    "aml314b/data/counterparty_directory.csv",
)
AML314B_ACTIVE_INVESTIGATIONS_PATH = os.getenv(
    "AML314B_ACTIVE_INVESTIGATIONS_PATH",
    "aml314b/fi_a/data/active_investigations.csv",
)
AML314B_RETRIEVED_INFORMATION_PATH = os.getenv(
    "AML314B_RETRIEVED_INFORMATION_PATH",
    "aml314b/fi_a/data/retrieved_information.csv",
)
AML314B_MESSAGE_TRANSPORT = os.getenv("AML314B_MESSAGE_TRANSPORT", "SLIM").upper()
AML314B_TRANSPORT_SERVER_ENDPOINT = os.getenv(
    "AML314B_TRANSPORT_SERVER_ENDPOINT",
    TRANSPORT_SERVER_ENDPOINT,
)
AML314B_PROBE_TRANSPORT = os.getenv("AML314B_PROBE_TRANSPORT", "NATS").upper()
AML314B_PROBE_NATS_ENDPOINT = os.getenv(
    "AML314B_PROBE_NATS_ENDPOINT",
    TRANSPORT_SERVER_ENDPOINT,
)
AML314B_PROBE_RESPONSE_TIMEOUT_MS = int(
    os.getenv("AML314B_PROBE_RESPONSE_TIMEOUT_MS", "500")
)
AML314B_DEFAULT_REQUESTER_INSTITUTION_ID = os.getenv(
    "AML314B_DEFAULT_REQUESTER_INSTITUTION_ID",
    "FI_A",
)
AML314B_DEFAULT_DISCOVERY_COHORT = ("FI_B", "FI_C", "FI_D", "FI_E", "FI_F")

# This is for demo purposes only. In production, use secure methods to manage API keys.
IDENTITY_API_KEY = os.getenv("IDENTITY_API_KEY", "487>t:7:Ke5N[kZ[dOmDg2]0RQx))6k}bjARRN+afG3806h(4j6j[}]F5O)f[6PD")
IDENTITY_API_SERVER_URL = os.getenv("IDENTITY_API_SERVER_URL", "https://api.agent-identity.outshift.com")
