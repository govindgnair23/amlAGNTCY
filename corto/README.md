# Corto: Bilateral AML 314(b)

`corto/` is the bilateral AML sample in this repository. It models one requesting institution (`FI_A`) and one responding institution (`FI_B`) exchanging bounded Section 314(b) case context through a deterministic enforcement layer.

The implementation covers:

- frozen 314(b) request and response schemas
- CSV-backed case, entity, context, and retrieval stores
- deterministic enforcement hooks on every send and receive path
- optional layered disclosure enforcement for Phase 2.b
- a standalone AML UI under `aml314b/frontend/`

## Repository Layout

- `aml314b/`
  Shared schemas, stores, enforcement, bilateral runner, and architecture notes
- `fi_a/`
  Requesting institution service and A2A client path
- `fi_b/`
  Responding institution service, A2A server path, and risk/disclosure logic
- `tests/`
  Focused AML integration and unit coverage

## Local Setup

Run from `corto/`:

```bash
uv venv
source .venv/bin/activate
uv sync --extra dev
cp .env.example .env
```

## Fastest Demo

Run the in-process bilateral flow without starting separate services:

```bash
uv run python aml314b/demo.py
```

This exercises FI-A request construction, FI-B evaluation, enforcement on both sides, and persistence into the retrieved-information store.

## Two-Service Demo

Terminal 1:

```bash
AML314B_MESSAGE_TRANSPORT=A2A uv run python fi_b/a2a_server.py
```

Terminal 2:

```bash
AML314B_MESSAGE_TRANSPORT=A2A uv run python fi_a/main.py
```

Useful FI-A endpoints:

- `POST /aml314b/run`
- `POST /aml314b/run/{case_id}`
- `GET /aml314b/retrieved`
- `GET /aml314b/logs`
- `GET /aml314b/steps`
- `GET /health`

## Minimal Docker Compose

```bash
docker compose up --build
```

The compose file is AML-only. It starts:

- `slim`
- `aml-fi-a`
- `aml-fi-b`

`FI_A` is exposed on `http://127.0.0.1:8011`. The compose-specific directory file routes SLIM traffic to the internal `slim` service and disables tracing and LLM-dependent risk classification for deterministic local runs.

## AML UI

Run the backend first, then start the standalone frontend:

```bash
cd aml314b/frontend
npm install
VITE_AML_API_BASE_URL=http://127.0.0.1:8011 npm run dev
```

## Focused Validation

```bash
SKIP_SESSION_SERVICES=true uv run pytest -s \
  tests/integration/test_aml314b_bilateral.py \
  tests/integration/test_aml314b_phase1b.py \
  tests/integration/test_aml314b_directory_lookup.py \
  tests/integration/test_aml314b_a2a_http.py \
  tests/integration/test_aml314b_phase2b_layered_disclosure.py \
  tests/unit/test_aml314b_enforcement_disclosure.py
```

```bash
cd aml314b/frontend
npm run build
```

## Key Configuration

The main AML runtime knobs live in `config/config.py`.

- `AML314B_MESSAGE_TRANSPORT`
- `AML314B_TRANSPORT_SERVER_ENDPOINT`
- `AML314B_REQUESTOR_HOST`
- `AML314B_REQUESTOR_PORT`
- `AML314B_RESPONDER_HOST`
- `AML314B_RESPONDER_PORT`
- `AML314B_DIRECTORY_PATH`
- `AML314B_ACTIVE_INVESTIGATIONS_PATH`
- `AML314B_RETRIEVED_INFORMATION_PATH`
- `AML314B_INTERNAL_INVESTIGATIONS_PATH`
- `AML314B_USE_LLM_RISK_CLASSIFIER`
- `AML314B_ENABLE_LAYERED_DISCLOSURE`
- `AML314B_UI_STEP_DELAY_SECONDS`

## Notes

- The detailed bilateral architecture write-up lives in `aml314b/ARCHITECTURE.md`.
- This sample is adapted from AGNTCY reference code, but the public surface here is intentionally limited to the AML flow.
