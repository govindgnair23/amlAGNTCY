# amlAGNTCY

`amlAGNTCY` is an AML-first adaptation of AGNTCY reference agents. It is organized around two Section 314(b) samples:

- `corto/`: bilateral AML information sharing between `FI_A` and `FI_B`
- `lungo/`: multilateral AML discovery and scoped collaboration across `FI_A` through `FI_F`

The repository intentionally keeps only the AML runtime, tests, frontends, and minimum compose/config assets needed to run and validate those samples.

## Upstream Reference

This repository is adapted from the original AGNTCY sample repository:
[agntcy/coffeeAgntcy](https://github.com/agntcy/coffeeAgntcy).

Use the upstream repository for the broader non-AML AGNTCY context. This repository documents and publishes only the AML-focused adaptation.

## Repository Layout

- `corto/`
  Bilateral runtime, enforcement, tests, and AML UI
- `lungo/`
  Multilateral discovery/collaboration runtime, tests, and AML UI

## Prerequisites

- Python `3.13`
- `uv`
- `npm` for the frontend builds
- Docker Engine with Docker Compose for the containerized flows
- Provider credentials configured via the sample `.env.example` files

The complete Python dependency sets live in [`corto/pyproject.toml`](/Users/learningmachine/Documents/Python-dev/AML_AGNTCY/coffeeAgntcy/amlAGNTCY/corto/pyproject.toml) and [`lungo/pyproject.toml`](/Users/learningmachine/Documents/Python-dev/AML_AGNTCY/coffeeAgntcy/amlAGNTCY/lungo/pyproject.toml).

## Setup

Each sample is self-contained and uses `uv`.

```bash
cd corto
uv venv
source .venv/bin/activate
uv sync --extra dev
```

Repeat the same setup in `lungo/` when working on the multilateral sample.

## Validation

### Corto

```bash
cd corto
SKIP_SESSION_SERVICES=true uv run pytest -s \
  tests/integration/test_aml314b_bilateral.py \
  tests/integration/test_aml314b_phase1b.py \
  tests/integration/test_aml314b_directory_lookup.py \
  tests/integration/test_aml314b_a2a_http.py \
  tests/integration/test_aml314b_phase2b_layered_disclosure.py \
  tests/unit/test_aml314b_enforcement_disclosure.py
```

```bash
cd corto/aml314b/frontend
npm run build
```

### Lungo

```bash
cd lungo
SKIP_SESSION_SERVICES=true uv run pytest -s \
  tests/integration/test_aml_discovery_supervisor.py \
  tests/integration/test_aml_group_collaboration.py \
  tests/integration/test_aml_investigation_transport_segmentation.py
```

```bash
cd lungo/aml314b/frontend
npm run build
```

## Attribution

This repository is adapted from AGNTCY examples, but the published surface here is intentionally rewritten around AML-only workflows and sample institutions.
