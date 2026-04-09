# AML314B Architecture

## Summary

The AML314B lane is organized around two agent services and a shared domain layer:

- `FI_A_Agent` reads active investigations, resolves counterparty routes, enforces outbound and inbound policy checks, sends requests, and persists retrieved responses.
- `FI_B_Agent` receives requests, enforces policy checks, evaluates entity, context, and risk data, optionally applies layered disclosure review, and returns bounded responses.
- `aml314b/` provides the shared schemas, stores, placeholder enforcement layer, step-event utilities, and optional layered disclosure enforcement modules.
- `aml314b/frontend/` polls `FI_A` APIs for run status, logs, steps, and retrieved information.

## Component Inventory

- Shared contracts and persistence: `aml314b/schemas.py`, `aml314b/stores.py`
- Shared baseline enforcement: `aml314b/enforcement.py`
- Optional layered disclosure enforcement: `aml314b/enforcement_disclosure/`
- `FI_A_Agent` orchestration: `fi_a/agent.py`
- `FI_A` API surface: `fi_a/main.py`
- `FI_A` transport adapter: `fi_a/a2a_client.py`
- `FI_B_Agent` orchestration: `fi_b/agent.py`
- `FI_B` transport server: `fi_b/a2a_server.py`
- `FI_B` A2A executor: `fi_b/agent_executor.py`
- AML UI: `aml314b/frontend/src/App.tsx`
- In-process demo harness: `aml314b/bilateral.py`

## Mermaid Diagram

```mermaid

flowchart LR
    User[Analyst / Demo User]
    UI[AML UI\naml314b/frontend]
    FI_A_API[FI_A FastAPI Service\nfi_a/main.py]
    FI_A_Agent[FI_A_Agent\nfi_a/agent.py]
    FI_A_Enforcement[Placeholder Enforcement\nFI_A outbound/inbound]
    ActiveStore[ActiveInvestigationsStore\nfi_a/data/active_investigations.csv]
    DirectoryStore[CounterpartyDirectoryStore\naml314b/data/counterparty_directory.csv]
    RetrievedStore[RetrievedInformationStore\nfi_a/data/retrieved_information.csv]
    LogStep[LogBuffer + StepEventBuffer]
    Transport[A2A Client / AGNTCY Transport\nfi_a/a2a_client.py]
    FI_B_Server[FI_B A2A Server\nfi_b/a2a_server.py]
    FI_B_Executor[AMLResponderExecutor\nfi_b/agent_executor.py]
    FI_B_Agent[FI_B_Agent\nfi_b/agent.py]
    FI_B_Enforcement[Placeholder Enforcement\nFI_B inbound/outbound]
    KnownStore[KnownHighRiskEntitiesStore\nfi_b/data/known_high_risk_entities.csv]
    CuratedStore[CuratedInvestigativeContextStore\nfi_b/data/curated_investigative_context.csv]
    InternalStore[InternalInvestigationsTriggerStore\nfi_b/data/internal_investigations.csv]
    Risk[Risk Classifier\nDeterministic or LLM]
    Layered[LayeredDisclosureEnforcer]
    DetLayer[Deterministic Policy Layer]
    SemLayer[Single-Turn Semantic Layer]
    CumLayer[Cumulative Semantic Layer]
    Critic[LLMDisclosureCritic]
    AuditStore[DisclosureAuditStore\nfi_b/data/disclosure_audit.csv]
    Shared[Shared AML Contracts\naml314b/schemas.py]
    Demo[In-Process Demo Harness\naml314b/bilateral.py]

    User --> UI
    UI -->|POST run / GET logs,steps,retrieved| FI_A_API
    FI_A_API --> FI_A_Agent
    FI_A_API --> RetrievedStore
    FI_A_API --> LogStep

    FI_A_Agent --> ActiveStore
    FI_A_Agent --> DirectoryStore
    FI_A_Agent --> FI_A_Enforcement
    FI_A_Agent --> Transport
    FI_A_Agent --> RetrievedStore
    FI_A_Agent --> LogStep
    FI_A_Agent -. uses .-> Shared

    Transport -->|A2A / SLIM| FI_B_Server
    FI_B_Server --> FI_B_Executor
    FI_B_Executor --> FI_B_Agent
    FI_B_Executor -->|step events| Transport

    FI_B_Agent --> FI_B_Enforcement
    FI_B_Agent --> KnownStore
    FI_B_Agent --> CuratedStore
    FI_B_Agent --> Risk
    FI_B_Agent --> InternalStore
    FI_B_Agent -. uses .-> Shared

    FI_B_Agent --> Layered
    Layered --> DetLayer
    Layered --> SemLayer
    Layered --> CumLayer
    SemLayer --> Critic
    CumLayer --> Critic
    Layered --> AuditStore
    CumLayer --> AuditStore

    Demo --> FI_A_Agent
    Demo --> FI_B_Agent
    Demo -->|ASGITransport instead of network| Transport

```

## Runtime Notes

- `FI_A` reads `fi_a/data/active_investigations.csv` and resolves counterparties from `aml314b/data/counterparty_directory.csv`.
- `FI_A` persists successful inbound responses to `fi_a/data/retrieved_information.csv`.
- `FI_B` reads known entities and curated context from CSV-backed stores under `fi_b/data/`.
- If activity suggests risk without a known-entity match, `FI_B` can trigger `fi_b/data/internal_investigations.csv`.
- When layered disclosure is enabled, `FI_B` audits each disclosure review to `fi_b/data/disclosure_audit.csv`.
