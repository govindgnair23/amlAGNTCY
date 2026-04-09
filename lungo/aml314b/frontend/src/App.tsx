import { useEffect, useState } from "react";

type RunMode = "discovery" | "collaboration";
type InvestigationType = "MONEY_MULE" | "TERRORIST_FINANCING";

type LaneProbeResponse = {
  probe_id: string;
  responder_institution_id: string;
  investigation_type: InvestigationType;
  decision: "YES";
  responded_at: string;
};

type LaneProbeResult = {
  probe_id: string;
  investigation_type: InvestigationType;
  candidate_institutions: string[];
  candidate_response_count: number;
  candidate_resolution_source: "NATS_LANE_PROBE";
  responses: LaneProbeResponse[];
};

type ActiveCase = {
  case_id: string;
  investigation_type: InvestigationType;
  entity_id: string;
  entity_name: string;
  counterparty_id: string;
  time_window_start: string;
  time_window_end: string;
  status: string;
  case_summary: string;
};

type StepEvent = {
  id: number;
  case_id: string;
  investigation_type: InvestigationType;
  transport_lane: string | null;
  step_name: string;
  message: string;
  timestamp: string;
};

type DiscoveryResponse = {
  responder_institution_id: string;
  investigation_type: InvestigationType;
  transport_lane: string | null;
  decision: "ACCEPT" | "DECLINE";
  reason: string;
};

type DiscoveryAggregateResult = {
  discovery_session_id: string;
  investigation_type: InvestigationType;
  transport_lane: string | null;
  case_id: string;
  entity_id: string;
  entity_name: string;
  candidate_institutions: string[];
  candidate_response_count: number;
  candidate_resolution_source: "NATS_LANE_PROBE";
  accepted_institutions: string[];
  declined_institutions: string[];
  response_count: number;
  responses: DiscoveryResponse[];
};

type CollaborationParticipant = {
  institution_id: string;
  display_name: string;
  role: "ORIGINATOR" | "RESPONDER";
};

type CollaborationContribution = {
  investigation_type: InvestigationType;
  transport_lane: string | null;
  institution_id: string;
  contribution: string;
  sequence_number: number;
};

type CollaborationSessionResult = {
  session_id: string;
  investigation_type: InvestigationType;
  transport_lane: string | null;
  case_id: string;
  entity_id: string;
  entity_name: string;
  participants: CollaborationParticipant[];
  contributions: CollaborationContribution[];
  final_summary: string;
};

type Observability = {
  session_id: string | null;
  traceparent_id: string | null;
};

type RunState = {
  response: string;
  discoveryResult: DiscoveryAggregateResult | null;
  collaborationResult: CollaborationSessionResult | null;
  observability: Observability | null;
  stepEvents: StepEvent[];
};

type ProbeApiResponse = {
  probe_result?: LaneProbeResult;
  detail?: string;
};

type CasesApiResponse = {
  cases?: ActiveCase[];
  detail?: string;
};

type DiscoveryRunResponse = {
  response?: string;
  aggregate_result?: DiscoveryAggregateResult;
  step_events?: StepEvent[];
  observability?: Observability;
  detail?: string;
};

type CollaborationRunResponse = {
  response?: string;
  discovery_result?: DiscoveryAggregateResult;
  collaboration_result?: CollaborationSessionResult;
  step_events?: StepEvent[];
  observability?: Observability;
  detail?: string;
};

const INVESTIGATION_LABELS: Record<InvestigationType, string> = {
  MONEY_MULE: "Money mule",
  TERRORIST_FINANCING: "Terrorist financing",
};

const PROBE_STEP_NAMES = new Set([
  "lane_probe_sent",
  "lane_probe_response_received",
  "candidate_set_finalized",
]);

const DISCOVERY_STEP_NAMES = new Set([
  "discovery_request_created",
  "discovery_broadcast_sent",
  "institution_response_received",
  "discovery_result_set_finalized",
  "discovery_completed",
]);

const COLLABORATION_STEP_NAMES = new Set([
  "collaboration_session_created",
  "collaboration_participants_selected",
  "collaboration_contribution_received",
  "collaboration_completed",
]);

function formatTimestamp(value?: string) {
  if (!value) {
    return "Not available";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function formatInvestigationType(value?: InvestigationType | null) {
  if (!value) {
    return "Pending";
  }
  return INVESTIGATION_LABELS[value];
}

function formatWindow(start: string, end: string) {
  const startLabel = formatTimestamp(start);
  const endLabel = formatTimestamp(end);
  return `${startLabel} to ${endLabel}`;
}

function getEventPhase(stepName: string) {
  if (PROBE_STEP_NAMES.has(stepName)) {
    return "Probe";
  }
  if (DISCOVERY_STEP_NAMES.has(stepName)) {
    return "Discovery";
  }
  if (COLLABORATION_STEP_NAMES.has(stepName)) {
    return "Collaboration";
  }
  return "Workflow";
}

export default function App() {
  const apiBase = (import.meta.env.VITE_AML_API_BASE_URL ?? "http://127.0.0.1:9110").replace(
    /\/$/,
    "",
  );
  const [runMode, setRunMode] = useState<RunMode>("collaboration");
  const [selectedInvestigationType, setSelectedInvestigationType] =
    useState<InvestigationType>("MONEY_MULE");
  const [probeResult, setProbeResult] = useState<LaneProbeResult | null>(null);
  const [cases, setCases] = useState<ActiveCase[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [runState, setRunState] = useState<RunState | null>(null);
  const [loadingLane, setLoadingLane] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();

    async function loadLaneState() {
      setLoadingLane(true);
      setError(null);
      setProbeResult(null);
      setCases([]);
      setSelectedCaseId("");
      setRunState(null);

      try {
        const [probeResponse, casesResponse] = await Promise.all([
          fetch(`${apiBase}/agent/probe`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            signal: controller.signal,
            body: JSON.stringify({
              investigation_type: selectedInvestigationType,
            }),
          }),
          fetch(`${apiBase}/agent/cases?investigation_type=${selectedInvestigationType}`, {
            signal: controller.signal,
          }),
        ]);
        const probePayload = (await probeResponse.json()) as ProbeApiResponse;
        if (!probeResponse.ok) {
          throw new Error(probePayload.detail ?? "Lane probe failed.");
        }
        const casesPayload = (await casesResponse.json()) as CasesApiResponse;
        if (!casesResponse.ok) {
          throw new Error(casesPayload.detail ?? "Case listing failed.");
        }

        if (!active) {
          return;
        }

        const nextCases = casesPayload.cases ?? [];
        setProbeResult(probePayload.probe_result ?? null);
        setCases(nextCases);
        setSelectedCaseId(nextCases[0]?.case_id ?? "");
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") {
          return;
        }
        console.error(err);
        if (active) {
          setError(err instanceof Error ? err.message : "Unknown lane loading error.");
        }
      } finally {
        if (active) {
          setLoadingLane(false);
        }
      }
    }

    void loadLaneState();

    return () => {
      active = false;
      controller.abort();
    };
  }, [apiBase, selectedInvestigationType]);

  async function handleRun() {
    if (!selectedCaseId) {
      setError("Select a case before starting explicit discovery.");
      return;
    }

    setRunning(true);
    setError(null);

    try {
      const response = await fetch(`${apiBase}/agent/cases/run`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          case_id: selectedCaseId,
          investigation_type: selectedInvestigationType,
          run_mode: runMode,
          candidate_institutions: probeResult?.candidate_institutions ?? undefined,
        }),
      });

      if (runMode === "collaboration") {
        const payload = (await response.json()) as CollaborationRunResponse;
        if (!response.ok) {
          throw new Error(payload.detail ?? "AML collaboration run failed.");
        }
        setRunState({
          response: payload.response ?? "",
          discoveryResult: payload.discovery_result ?? null,
          collaborationResult: payload.collaboration_result ?? null,
          observability: payload.observability ?? null,
          stepEvents: [...(payload.step_events ?? [])].sort((left, right) => left.id - right.id),
        });
        return;
      }

      const payload = (await response.json()) as DiscoveryRunResponse;
      if (!response.ok) {
        throw new Error(payload.detail ?? "AML discovery run failed.");
      }
      setRunState({
        response: payload.response ?? "",
        discoveryResult: payload.aggregate_result ?? null,
        collaborationResult: null,
        observability: payload.observability ?? null,
        stepEvents: [...(payload.step_events ?? [])].sort((left, right) => left.id - right.id),
      });
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Unknown AML workflow error.");
    } finally {
      setRunning(false);
    }
  }

  const selectedCase = cases.find((caseItem) => caseItem.case_id === selectedCaseId) ?? null;
  const latestStep = runState?.stepEvents[runState.stepEvents.length - 1] ?? null;
  const discoveryResult = runState?.discoveryResult ?? null;
  const collaborationResult = runState?.collaborationResult ?? null;
  const acceptedCount = discoveryResult?.accepted_institutions.length ?? 0;
  const declinedCount = discoveryResult?.declined_institutions.length ?? 0;
  const participantCount = collaborationResult?.participants.length ?? 0;

  return (
    <div className="page-shell">
      <div className="background-orb background-orb-left" />
      <div className="background-orb background-orb-right" />
      <div className="page">
        <aside className="sidebar">
          <div className="brand-block">
            <p className="eyebrow">aml314(b)</p>
            <h1>Lane-First Workflow</h1>
            <p className="brand-copy">
              Probe the lane first, choose the active case second, and only then start explicit
              discovery or collaboration.
            </p>
          </div>

          <section className="panel sidebar-panel">
            <div className="panel-heading">
              <h2>Run Controls</h2>
              <span className="badge">Structured UI</span>
            </div>

            <label className="field">
              <span>Investigation type</span>
              <select
                value={selectedInvestigationType}
                onChange={(event) =>
                  setSelectedInvestigationType(event.target.value as InvestigationType)
                }
                disabled={loadingLane || running}
              >
                <option value="MONEY_MULE">Money mule</option>
                <option value="TERRORIST_FINANCING">Terrorist financing</option>
              </select>
            </label>

            <div className="hint-card">
              <p className="hint-label">Lane probe</p>
              <p>
                Selecting a lane triggers the coarse NATS shortlist before any case-scoped
                discovery request is sent.
              </p>
            </div>

            <div className="mode-toggle" role="tablist" aria-label="Run mode">
              <button
                type="button"
                className={runMode === "collaboration" ? "mode-button active" : "mode-button"}
                onClick={() => setRunMode("collaboration")}
              >
                Discovery + collaboration
              </button>
              <button
                type="button"
                className={runMode === "discovery" ? "mode-button active" : "mode-button"}
                onClick={() => setRunMode("discovery")}
              >
                Discovery only
              </button>
            </div>

            <button
              type="button"
              className="run-button"
              onClick={handleRun}
              disabled={loadingLane || running || !selectedCase}
            >
              {running
                ? "Running structured workflow..."
                : runMode === "collaboration"
                  ? "Run discovery + collaboration"
                  : "Run discovery"}
            </button>

            {error ? <p className="error-text">{error}</p> : null}
          </section>

          <section className="panel sidebar-panel">
            <div className="panel-heading">
              <h2>Flow Status</h2>
              <span className="badge muted">Lane first</span>
            </div>

            <div className="stage-rail">
              <div className={`stage-card ${loadingLane ? "active" : probeResult ? "complete" : "pending"}`}>
                <p className="stage-index">01</p>
                <div>
                  <p className="phase-title">Probe responders</p>
                  <p className="summary-copy">
                    {loadingLane
                      ? "Resolving the shortlist for the selected lane."
                      : probeResult
                        ? `${probeResult.candidate_response_count} institutions replied YES.`
                        : "No shortlist loaded yet."}
                  </p>
                </div>
              </div>

              <div className={`stage-card ${selectedCase ? "complete" : loadingLane ? "pending" : "active"}`}>
                <p className="stage-index">02</p>
                <div>
                  <p className="phase-title">Select case</p>
                  <p className="summary-copy">
                    {selectedCase
                      ? `${selectedCase.case_id} is staged for explicit discovery.`
                      : "Choose one of the active cases for the lane."}
                  </p>
                </div>
              </div>

              <div className={`stage-card ${running ? "active" : runState ? "complete" : "pending"}`}>
                <p className="stage-index">03</p>
                <div>
                  <p className="phase-title">Run workflow</p>
                  <p className="summary-copy">
                    {running
                      ? "Explicit discovery is in progress."
                      : runState?.response ?? "No case run has been executed yet."}
                  </p>
                </div>
              </div>
            </div>

            <div className="timeline-note">
              <p className="hint-label">Latest event</p>
              <p>{latestStep?.message ?? "Run the selected case to populate the AML timeline."}</p>
              <p className="timeline-time">{formatTimestamp(latestStep?.timestamp)}</p>
            </div>
          </section>
        </aside>

        <main className="content">
          <header className="hero panel">
            <div>
              <p className="eyebrow">Phase 3.e follow-on</p>
              <h2>Probe the lane, choose the case, then start discovery</h2>
              <p className="hero-copy">
                The UI no longer relies on prompt parsing. The lane probe is coarse and
                non-sensitive, the case list comes from FI_A&apos;s active investigations store,
                and the explicit workflow begins only after a specific case is selected.
              </p>
            </div>
            <div className="hero-metrics">
              <div className="metric-card">
                <p className="metric-label">Probe responders</p>
                <p className="metric-value">{probeResult?.candidate_response_count ?? 0}</p>
                <p className="metric-caption">
                  {probeResult?.candidate_institutions.join(", ") ?? "Waiting for lane selection"}
                </p>
              </div>
              <div className="metric-card">
                <p className="metric-label">Explicit acceptors</p>
                <p className="metric-value">{acceptedCount}</p>
                <p className="metric-caption">
                  {discoveryResult?.accepted_institutions.join(", ") ?? "Run discovery to resolve"}
                </p>
              </div>
              <div className="metric-card">
                <p className="metric-label">Collaboration cohort</p>
                <p className="metric-value">{participantCount || "N/A"}</p>
                <p className="metric-caption">
                  {collaborationResult?.participants
                    .map((participant) => participant.institution_id)
                    .join(", ") ?? "Only populated for collaboration runs"}
                </p>
              </div>
            </div>
          </header>

          <section className="summary-grid">
            <article className="panel summary-card">
              <div className="panel-heading">
                <h2>Probe Responders</h2>
                <span className="badge muted">
                  {probeResult?.candidate_resolution_source ?? "Awaiting probe"}
                </span>
              </div>
              <p className="summary-copy">
                The lane shortlist is resolved before the case run starts. Only these institutions
                are eligible for the later explicit discovery request.
              </p>
              <div className="pill-row">
                {(probeResult?.candidate_institutions ?? []).map((institutionId) => (
                  <span key={institutionId} className="pill candidate">
                    {institutionId}
                  </span>
                ))}
                {!probeResult?.candidate_institutions.length && !loadingLane ? (
                  <span className="pill muted-pill">No institutions responded to the lane probe.</span>
                ) : null}
              </div>
              <div className="response-table">
                <div className="table-head">
                  <span>Institution</span>
                  <span>Decision</span>
                  <span>Responded</span>
                </div>
                {(probeResult?.responses ?? []).map((response) => (
                  <div key={response.responder_institution_id} className="table-row">
                    <span>{response.responder_institution_id}</span>
                    <span>{response.decision}</span>
                    <span>{formatTimestamp(response.responded_at)}</span>
                  </div>
                ))}
                {!probeResult?.responses.length ? (
                  <div className="table-row empty-row">
                    <span>{formatInvestigationType(selectedInvestigationType)}</span>
                    <span>{loadingLane ? "Loading" : "Pending"}</span>
                    <span>The probe shortlist will appear here before any case run starts.</span>
                  </div>
                ) : null}
              </div>
            </article>

            <article className="panel summary-card">
              <div className="panel-heading">
                <h2>Active Cases</h2>
                <span className="badge muted">{cases.length} loaded</span>
              </div>
              <p className="summary-copy">
                Active investigations are filtered by the selected lane so the user chooses a case
                only after the lane probe completes.
              </p>
              <div className="case-list">
                {cases.map((caseItem) => (
                  <button
                    key={caseItem.case_id}
                    type="button"
                    className={selectedCaseId === caseItem.case_id ? "case-card active" : "case-card"}
                    onClick={() => setSelectedCaseId(caseItem.case_id)}
                    disabled={running}
                  >
                    <div className="case-card-header">
                      <div>
                        <p className="hint-label">Case</p>
                        <h3>{caseItem.case_id}</h3>
                      </div>
                      <span className="badge muted">{caseItem.status}</span>
                    </div>
                    <p className="case-entity">
                      {caseItem.entity_name} ({caseItem.entity_id})
                    </p>
                    <p className="summary-copy">{caseItem.case_summary}</p>
                    <p className="timeline-time">
                      Window: {formatWindow(caseItem.time_window_start, caseItem.time_window_end)}
                    </p>
                  </button>
                ))}
                {!cases.length && !loadingLane ? (
                  <div className="placeholder-card">
                    <p className="hint-label">No active cases</p>
                    <p>The selected lane returned no active cases from FI_A&apos;s store.</p>
                  </div>
                ) : null}
              </div>
            </article>
          </section>

          <section className="panel-grid">
            <article className="panel">
              <div className="panel-heading">
                <h2>Explicit Discovery Results</h2>
                <span className="badge muted">
                  {discoveryResult?.discovery_session_id ?? "Not started"}
                </span>
              </div>

              <div className="pill-row">
                {(discoveryResult?.accepted_institutions ?? []).map((institutionId) => (
                  <span key={institutionId} className="pill accept">
                    {institutionId} accepted
                  </span>
                ))}
                {(discoveryResult?.declined_institutions ?? []).map((institutionId) => (
                  <span key={institutionId} className="pill decline">
                    {institutionId} declined
                  </span>
                ))}
                {!acceptedCount && !declinedCount ? (
                  <span className="pill muted-pill">Awaiting explicit case discovery.</span>
                ) : null}
              </div>

              <div className="split-grid">
                <div className="list-card">
                  <p className="hint-label">Shortlisted institutions</p>
                  <ul className="simple-list">
                    {(discoveryResult?.candidate_institutions ??
                      probeResult?.candidate_institutions ??
                      []
                    ).map((institutionId) => (
                      <li key={institutionId}>{institutionId}</li>
                    ))}
                  </ul>
                </div>
                <div className="list-card">
                  <p className="hint-label">Selected case</p>
                  <p className="identifier">{selectedCase?.case_id ?? "Pending case selection"}</p>
                  <p className="summary-copy">
                    {selectedCase?.case_summary ??
                      "Pick a case to unlock explicit discovery and collaboration."}
                  </p>
                </div>
              </div>

              <div className="response-table">
                <div className="table-head">
                  <span>Institution</span>
                  <span>Decision</span>
                  <span>Reason</span>
                </div>
                {(discoveryResult?.responses ?? []).map((response) => (
                  <div key={response.responder_institution_id} className="table-row">
                    <span>{response.responder_institution_id}</span>
                    <span>{response.decision}</span>
                    <span>{response.reason}</span>
                  </div>
                ))}
                {!discoveryResult?.responses.length ? (
                  <div className="table-row empty-row">
                    <span>Shortlisted cohort</span>
                    <span>Pending</span>
                    <span>
                      Explicit accept or decline decisions appear only after the selected case is
                      run.
                    </span>
                  </div>
                ) : null}
              </div>
            </article>

            <article className="panel">
              <div className="panel-heading">
                <h2>Collaboration Participants</h2>
                <span className="badge muted">
                  {collaborationResult?.session_id ?? "Awaiting scoped session"}
                </span>
              </div>

              <div className="pill-row">
                {(collaborationResult?.participants ?? []).map((participant) => (
                  <span key={participant.institution_id} className="pill participant">
                    {participant.institution_id} · {participant.role}
                  </span>
                ))}
                {!collaborationResult ? (
                  <span className="pill muted-pill">
                    Collaboration appears only when the structured run mode includes it.
                  </span>
                ) : null}
              </div>

              {collaborationResult ? (
                <>
                  <div className="list-card">
                    <p className="hint-label">Deterministic contributions</p>
                    <ol className="number-list">
                      {collaborationResult.contributions.map((contribution) => (
                        <li key={contribution.institution_id}>
                          <strong>{contribution.institution_id}</strong>
                          <span>{contribution.contribution}</span>
                        </li>
                      ))}
                    </ol>
                  </div>
                  <div className="list-card">
                    <p className="hint-label">Final summary</p>
                    <p className="summary-copy">{collaborationResult.final_summary}</p>
                  </div>
                </>
              ) : (
                <div className="placeholder-card">
                  <p className="hint-label">Scoped cohort</p>
                  <p>
                    Run the collaboration path after selecting a case to confirm that only explicit
                    acceptors join the final session.
                  </p>
                </div>
              )}
            </article>
          </section>

          <section className="panel-grid">
            <article className="panel">
              <div className="panel-heading">
                <h2>Observability</h2>
                <span className="badge muted">Trace lookup</span>
              </div>
              <div className="observability-grid">
                <div className="list-card">
                  <p className="hint-label">Investigation type</p>
                  <p className="identifier">
                    {formatInvestigationType(
                      discoveryResult?.investigation_type ??
                        collaborationResult?.investigation_type ??
                        selectedInvestigationType,
                    )}
                  </p>
                </div>
                <div className="list-card">
                  <p className="hint-label">Transport lane</p>
                  <p className="identifier">
                    {discoveryResult?.transport_lane ??
                      collaborationResult?.transport_lane ??
                      "A2A compatibility path"}
                  </p>
                </div>
                <div className="list-card">
                  <p className="hint-label">Probe ID</p>
                  <p className="identifier">{probeResult?.probe_id ?? "Pending"}</p>
                </div>
                <div className="list-card">
                  <p className="hint-label">Observe session ID</p>
                  <p className="identifier">{runState?.observability?.session_id ?? "Pending"}</p>
                </div>
                <div className="list-card">
                  <p className="hint-label">Traceparent ID</p>
                  <p className="identifier">
                    {runState?.observability?.traceparent_id ?? "Pending"}
                  </p>
                </div>
                <div className="list-card">
                  <p className="hint-label">Discovery session ID</p>
                  <p className="identifier">
                    {discoveryResult?.discovery_session_id ?? "Pending"}
                  </p>
                </div>
              </div>
            </article>

            <article className="panel">
              <div className="panel-heading">
                <h2>Ordered Step Events</h2>
                <span className="badge muted">{runState?.stepEvents.length ?? 0} events</span>
              </div>
              <div className="event-list">
                {(runState?.stepEvents ?? []).map((event) => (
                  <div key={event.id} className="event-row">
                    <div className="event-meta">
                      <span className="event-phase">{getEventPhase(event.step_name)}</span>
                      <span className="event-step">{event.step_name}</span>
                    </div>
                    <p>{event.message}</p>
                    <p className="timeline-time">
                      {formatInvestigationType(event.investigation_type)}
                      {event.transport_lane ? ` · ${event.transport_lane}` : ""}
                    </p>
                    <p className="timeline-time">{formatTimestamp(event.timestamp)}</p>
                  </div>
                ))}
                {!runState?.stepEvents.length ? (
                  <div className="event-row empty-row">
                    <div className="event-meta">
                      <span className="event-phase">Workflow</span>
                      <span className="event-step">awaiting_run</span>
                    </div>
                    <p>The case-scoped timeline begins only after the selected case is run.</p>
                    <p className="timeline-time">Not started</p>
                  </div>
                ) : null}
              </div>
            </article>
          </section>
        </main>
      </div>
    </div>
  );
}
