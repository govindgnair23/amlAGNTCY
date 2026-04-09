# Lungo: Multilateral AML 314(b)

`lungo/` is the multilateral AML sample in this repository. It now models one originating institution (`FI_A`) first publishing a coarse lane probe over NATS, then sending explicit case-scoped discovery only to the institutions that replied `YES`, and finally forming a scoped collaboration session with only the responders that accept.

The implementation covers:

- deterministic discovery across `FI_B` through `FI_F`
- NATS lane probing with responder-local membership configuration
- scoped collaboration derived from discovery acceptances
- investigation-type routing for `MONEY_MULE` and `TERRORIST_FINANCING`
- lane-aware SLIM topics plus direct `A2A` compatibility
- a standalone AML UI under `aml314b/frontend/`

## Repository Layout

- `aml314b/common/`
  Shared schemas, stores, enforcement helpers, channeling, and step events
- `aml314b/fi_a/`
  Supervisor API and orchestration graph
- `aml314b/institutions/`
  Thin responder runtimes for `FI_B` through `FI_F`
- `aml314b/frontend/`
  AML-only browser UI
- `tests/`
  Focused AML integration coverage

## Seeded Investigation Types

- `MONEY_MULE`
  `CASE-JOHN-01` / `ENTITY-JOHN-01`
  Probe members: `FI_B`, `FI_C`, `FI_D`, `FI_E`
  Acceptors: `FI_B`, `FI_C`, `FI_D`
- `TERRORIST_FINANCING`
  `CASE-SAFIYA-01` / `ENTITY-SAFIYA-01`
  Probe members: `FI_B`, `FI_C`, `FI_D`, `FI_F`
  Acceptors after explicit discovery: `FI_C`, `FI_F`

`FI_E` still has seeded terrorist-financing case data, but it is not lane-subscribed for that category, so it no longer receives the explicit case discovery request in Phase 3E.

## Probe Stage

The Phase 3E workflow is intentionally split into three steps:

1. `FI_A` publishes a coarse lane probe on `aml314b.probe.money_mule` or `aml314b.probe.terrorist_financing`.
2. Only responder institutions locally configured for that lane subscribe and reply `YES`.
3. `FI_A` sends the existing explicit `DiscoveryRequest` only to that candidate set, and collaboration still starts only from later `ACCEPT` responders.

The lane probe is not a group session. It carries no `case_id`, `entity_id`, `entity_name`, or `case_context`.

## Local Setup

Run from `lungo/`:

```bash
uv venv
source .venv/bin/activate
uv sync --extra dev
cp .env.example .env
```

## Run With A2A

Start a NATS server first for the probe stage:

```bash
docker run --rm -p 4222:4222 nats:latest
```

Start the responders and supervisor in separate terminals:

```bash
AML314B_MESSAGE_TRANSPORT=A2A uv run python aml314b/institutions/fi_b/server.py
AML314B_MESSAGE_TRANSPORT=A2A uv run python aml314b/institutions/fi_c/server.py
AML314B_MESSAGE_TRANSPORT=A2A uv run python aml314b/institutions/fi_d/server.py
AML314B_MESSAGE_TRANSPORT=A2A uv run python aml314b/institutions/fi_e/server.py
AML314B_MESSAGE_TRANSPORT=A2A uv run python aml314b/institutions/fi_f/server.py
AML314B_MESSAGE_TRANSPORT=A2A uv run python aml314b/fi_a/main.py
```

By default:

- `FI_A` listens on `http://127.0.0.1:9110`
- responders listen on `http://127.0.0.1:9120` through `http://127.0.0.1:9124`

## Run With SLIM

Start a NATS server first for the probe stage:

```bash
docker run --rm -p 4222:4222 nats:latest
```

```bash
AML314B_MESSAGE_TRANSPORT=SLIM uv run python aml314b/institutions/fi_b/server.py
AML314B_MESSAGE_TRANSPORT=SLIM uv run python aml314b/institutions/fi_c/server.py
AML314B_MESSAGE_TRANSPORT=SLIM uv run python aml314b/institutions/fi_d/server.py
AML314B_MESSAGE_TRANSPORT=SLIM uv run python aml314b/institutions/fi_e/server.py
AML314B_MESSAGE_TRANSPORT=SLIM uv run python aml314b/institutions/fi_f/server.py
AML314B_MESSAGE_TRANSPORT=SLIM uv run python aml314b/fi_a/main.py
```

In `SLIM`, each investigation type resolves to a distinct transport lane:

- `aml314b.money_mule`
- `aml314b.terrorist_financing`

## Minimal Docker Compose

```bash
docker compose up --build
```

This compose file is designed for a single local AML stack at a time. It pins explicit container names such as `lungo-aml314b-slim` and `lungo-aml314b-fi-c`, so running `docker compose up --build` again from another terminal or session will collide with the existing containers instead of creating a second isolated stack.

Use this workflow:

1. Start the stack once with `docker compose up --build`.
2. In other terminals, inspect the existing stack with `docker compose ps`, `docker compose logs -f`, or `docker compose exec <service> sh`.
3. When you want a clean restart, stop and remove the current stack with `docker compose down`.
4. Start it again with `docker compose up --build`.

If Compose reports a conflict such as `container name "/lungo-aml314b-slim" is already in use`, an old container still exists. From `lungo/`, run:

```bash
docker compose down
docker ps -a | grep 'lungo-aml314b-'
docker rm -f lungo-aml314b-slim lungo-aml314b-fi-a lungo-aml314b-fi-b lungo-aml314b-fi-c lungo-aml314b-fi-d lungo-aml314b-fi-e lungo-aml314b-fi-f 2>/dev/null || true
docker compose up --build
```

Notes:

- `docker compose down` is the preferred cleanup because it removes the full AML stack cleanly.
- `docker rm -f ...` is only needed if one or more old containers were left behind and continue to block startup.
- Using a different Compose project name does not avoid this conflict while `container_name` is hard-coded in `docker-compose.yaml`.

The compose file starts only:

- `nats`
- `slim`
- `aml-fi-a`
- `aml-fi-b`
- `aml-fi-c`
- `aml-fi-d`
- `aml-fi-e`
- `aml-fi-f`

`FI_A` is exposed on `http://127.0.0.1:9110`. The compose path is backend-only; run the AML UI separately when needed.

## AML UI

```bash
cd aml314b/frontend
npm install
VITE_AML_API_BASE_URL=http://127.0.0.1:9110 npm run dev
```

The UI supports discovery-only and discovery-plus-collaboration runs, investigation-type selection, responder cohorts, collaboration participants, and lane-aware step-event display.

The primary UI path is now lane-first:

1. select `Money mule` or `Terrorist financing`
2. review the coarse probe responders returned from `POST /agent/probe`
3. choose one of the active cases returned by `GET /agent/cases?investigation_type=...`
4. start the structured case workflow through `POST /agent/cases/run`

The prompt endpoints remain available as compatibility paths, but the browser UI no longer depends on prompt parsing for the seeded AML cases.

## Example API Call

```bash
curl -X POST http://127.0.0.1:9110/agent/probe \
  -H "Content-Type: application/json" \
  -d '{
    "investigation_type": "MONEY_MULE"
  }'
```

```bash
curl "http://127.0.0.1:9110/agent/cases?investigation_type=MONEY_MULE"
```

```bash
curl -X POST http://127.0.0.1:9110/agent/cases/run \
  -H "Content-Type: application/json" \
  -d '{
    "case_id": "CASE-JOHN-01",
    "investigation_type": "MONEY_MULE",
    "run_mode": "collaboration",
    "candidate_institutions": ["FI_B", "FI_C", "FI_D", "FI_E"]
  }'
```

## Focused Validation

```bash
SKIP_SESSION_SERVICES=true uv run pytest -s \
  tests/integration/test_aml_discovery_supervisor.py \
  tests/integration/test_aml_group_collaboration.py \
  tests/integration/test_aml_investigation_transport_segmentation.py \
  tests/integration/test_aml_lane_probe.py
```

```bash
cd aml314b/frontend
npm run build
```

## Key Configuration

The main AML runtime knobs live in `config/config.py`.

- `AML314B_MESSAGE_TRANSPORT`
- `AML314B_TRANSPORT_SERVER_ENDPOINT`
- `AML314B_PROBE_TRANSPORT`
- `AML314B_PROBE_NATS_ENDPOINT`
- `AML314B_PROBE_RESPONSE_TIMEOUT_MS`
- `AML314B_DISCOVERY_REQUESTOR_HOST`
- `AML314B_DISCOVERY_REQUESTOR_PORT`
- `AML314B_DISCOVERY_RESPONDER_BASE_PORT`
- `AML314B_DIRECTORY_PATH`
- `AML314B_ACTIVE_INVESTIGATIONS_PATH`
- `AML314B_RETRIEVED_INFORMATION_PATH`
- `AML314B_DEFAULT_REQUESTER_INSTITUTION_ID`

## Notes

- `aml314b/README.md` provides a shorter technical reference for the AML subtree.
- This sample is adapted from AGNTCY reference code, but the published surface here is intentionally limited to the AML workflow.
