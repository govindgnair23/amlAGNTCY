# AML 314(b) Subtree Reference

This subtree contains the multilateral AML runtime used by `lungo/`.

## Main Paths

- `common/`
  Shared schemas, stores, enforcement helpers, lane resolution, and step events
- `fi_a/`
  Discovery and collaboration supervisor API
- `institutions/common/`
  Shared responder runtime and agent adapters
- `institutions/fi_b` through `institutions/fi_f`
  Thin institution wrappers plus local CSV fixtures
- `frontend/`
  Standalone AML browser UI

## Supported Modes

- `NATS`
  Used for the coarse lane-probe stage on `aml314b.probe.money_mule` and
  `aml314b.probe.terrorist_financing`
- `A2A`
  Uses direct responder endpoints for explicit case discovery and collaboration, while preserving `investigation_type` without a lane name
- `SLIM`
  Uses lane-specific topics for explicit case discovery and collaboration, and returns lane metadata such as `aml314b.money_mule`

## Probe-Driven Flow

1. `FI_A` publishes a coarse lane probe over `NATS`.
2. Only lane-subscribed responders reply `YES`.
3. The structured UI and API list only the active FI_A cases for the selected lane.
4. `FI_A` sends explicit `DiscoveryRequest` payloads only to that candidate set once the user selects a specific case.
5. Collaboration still starts only from explicit `ACCEPT` responders.

The lane probe is not a group session and carries no case-specific fields.

## Structured FI_A Endpoints

- `POST /agent/probe`
  Returns the coarse shortlist for an `investigation_type`
- `GET /agent/cases?investigation_type=...`
  Returns the active seeded FI_A cases for that lane
- `POST /agent/cases/run`
  Runs explicit discovery or discovery plus collaboration from `case_id`, `investigation_type`, and `run_mode`

`POST /agent/prompt` and `POST /agent/prompt/collaboration` still exist as compatibility paths for the older prompt-driven workflow.

## Focused Tests

```bash
SKIP_SESSION_SERVICES=true uv run pytest -s \
  tests/integration/test_aml_discovery_supervisor.py \
  tests/integration/test_aml_group_collaboration.py \
  tests/integration/test_aml_investigation_transport_segmentation.py \
  tests/integration/test_aml_lane_probe.py
```
