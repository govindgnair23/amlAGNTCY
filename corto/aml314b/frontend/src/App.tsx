import { useEffect, useMemo, useRef, useState } from "react";

type LogEntry = {
  id: number;
  timestamp: string;
  level: string;
  logger: string;
  message: string;
};

type StepEvent = {
  id: number;
  case_id: string;
  step_name: string;
  message: string;
  timestamp: string;
};

type RetrievedRecord = {
  case_id: string;
  match_type: string;
  summary: string;
  received_at?: string;
  source_institution?: string;
};

type RunResult = {
  status: string;
  case_id: string | null;
  match_type: string | null;
  summary: string | null;
  error_message: string | null;
};

const CASE_OPTIONS = [
  {
    id: "CASE-JOHN-01",
    label: "John Doe / confirmed match",
    summary: "Cash deposits sent via Zelle to FI-B over two weeks.",
  },
  {
    id: "CASE-JOHN-SSN",
    label: "John Doe / SSN-blocked response",
    summary: "Same pattern; responder response should be blocked by enforcement.",
  },
  {
    id: "CASE-JANE-01",
    label: "Jane Doe / no match",
    summary: "Review of Jane Doe activity; no high-risk indicators.",
  },
  {
    id: "CASE-JIM-01",
    label: "Jim Doe / partial match",
    summary: "Structured cash deposits across a two-week window.",
  },
  {
    id: "CASE-JIMMY-01",
    label: "Jimmy Doe / high-risk escalation",
    summary: "Activity suggests possible terrorist financing patterns.",
  },
];

const STEP_SEQUENCE = [
  { name: "fi_a_preparing_request", label: "FI-A preparing request" },
  {
    name: "fi_a_outbound_reviewed",
    label: "FI-A outbound request reviewed for policy violation",
  },
  { name: "fi_a_request_sent", label: "FI-A request sent" },
  { name: "fi_b_preparing_response", label: "FI-B preparing response" },
  {
    name: "fi_b_response_reviewed",
    label: "FI-B response reviewed for policy violation",
  },
  { name: "fi_b_response_sent", label: "FI-B response sent" },
  { name: "fi_a_response_received", label: "FI-A received response" },
];

function formatTimestamp(value?: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export default function App() {
  const apiBase = useMemo(() => {
    const raw = import.meta.env.VITE_AML_API_BASE_URL as string | undefined;
    return (raw ?? "http://127.0.0.1:8011").replace(/\/$/, "");
  }, []);

  const [selectedCase, setSelectedCase] = useState(CASE_OPTIONS[0].id);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [retrieved, setRetrieved] = useState<RetrievedRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const logCursorRef = useRef<number | null>(null);
  const [steps, setSteps] = useState<StepEvent[]>([]);

  const selectedMeta = CASE_OPTIONS.find((item) => item.id === selectedCase);
  const lastLog = logs[logs.length - 1];

  const fetchRetrieved = async () => {
    try {
      const response = await fetch(`${apiBase}/aml314b/retrieved`);
      if (!response.ok) {
        throw new Error(`Retrieved information request failed (${response.status})`);
      }
      const data = (await response.json()) as RetrievedRecord[];
      setRetrieved(data);
    } catch (err) {
      console.error(err);
      setError("Unable to load retrieved information.");
    }
  };

  const pollLogs = async () => {
    try {
      const url = new URL(`${apiBase}/aml314b/logs`);
      if (logCursorRef.current !== null) {
        url.searchParams.set("since_id", String(logCursorRef.current));
      }
      const response = await fetch(url.toString());
      if (!response.ok) {
        throw new Error(`Log poll failed (${response.status})`);
      }
      const data = (await response.json()) as LogEntry[];
      if (Array.isArray(data) && data.length) {
        logCursorRef.current = data[data.length - 1].id;
        setLogs((prev) => {
          const combined = [...prev, ...data];
          return combined.slice(Math.max(combined.length - 500, 0));
        });
      }
    } catch (err) {
      console.error(err);
      setError("Unable to fetch log entries.");
    }
  };

  const pollSteps = async () => {
    try {
      const url = new URL(`${apiBase}/aml314b/steps`);
      url.searchParams.set("case_id", selectedCase);
      const response = await fetch(url.toString());
      if (!response.ok) {
        throw new Error(`Step poll failed (${response.status})`);
      }
      const data = (await response.json()) as StepEvent[];
      if (Array.isArray(data)) {
        const sorted = [...data].sort((left, right) => left.id - right.id);
        setSteps(sorted);
      }
    } catch (err) {
      console.error(err);
      setError("Unable to fetch step events.");
    }
  };

  const runCase = async () => {
    setRunning(true);
    setError(null);
    setSteps([]);
    try {
      const response = await fetch(`${apiBase}/aml314b/run/${selectedCase}`, {
        method: "POST",
      });
      const payload = (await response.json()) as RunResult;
      if (!response.ok) {
        const detail = (payload as unknown as { detail?: string }).detail;
        throw new Error(detail ?? "Case run failed");
      }
      setRunResult(payload);
      await fetchRetrieved();
      await pollLogs();
      await pollSteps();
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Unknown error running case");
    } finally {
      setRunning(false);
    }
  };

  useEffect(() => {
    setSteps([]);
  }, [selectedCase]);

  useEffect(() => {
    fetchRetrieved();
    pollLogs();
    pollSteps();
    const interval = window.setInterval(pollLogs, 1500);
    const stepInterval = window.setInterval(pollSteps, 1500);
    return () => {
      window.clearInterval(interval);
      window.clearInterval(stepInterval);
    };
  }, [apiBase, selectedCase]);

  const stepsForRun = useMemo(() => {
    if (!steps.length) return [];
    let startId: number | null = null;
    for (let i = steps.length - 1; i >= 0; i -= 1) {
      if (steps[i].step_name === "fi_a_preparing_request") {
        startId = steps[i].id;
        break;
      }
    }
    if (startId === null) return steps;
    return steps.filter((step) => step.id >= startId);
  }, [steps]);

  const completedSteps = new Set(stepsForRun.map((step) => step.step_name));
  const latestStep = stepsForRun[stepsForRun.length - 1];

  return (
    <div className="page">
      <div className="layout">
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-icon">A</span>
            <span>amlAGNTCY</span>
          </div>
          <div className="nav">
            <p className="nav-label">Conversation</p>
            <p className="nav-title">AML 314(b)</p>
            <button className="nav-pill">Agent to Agent</button>
          </div>
          <div className="status-panel">
            <div className="status-header">
              <h3>Run Status</h3>
              <span className="pill">Live</span>
            </div>
            <p className="status-subtitle">{selectedCase}</p>
            <div className="status-list">
              {STEP_SEQUENCE.map((step) => {
                const isComplete = completedSteps.has(step.name);
                const isActive = latestStep?.step_name === step.name;
                return (
                  <div
                    key={step.name}
                    className={`status-item ${isComplete ? "complete" : ""} ${
                      isActive ? "active" : ""
                    }`}
                  >
                    <span className="status-dot" />
                    <span>{step.label}</span>
                  </div>
                );
              })}
            </div>
            {latestStep ? (
              <div className="status-latest">
                <p className="status-latest-label">Latest</p>
                <p>{latestStep.message}</p>
                <p className="status-time">{formatTimestamp(latestStep.timestamp)}</p>
              </div>
            ) : (
              <p className="empty">Run a case to see step progress.</p>
            )}
          </div>
        </aside>

        <main className="content">
          <header className="hero">
            <div>
              <p className="eyebrow">AML 314(b) Demo</p>
              <h1>FI-A &lt;-&gt; FI-B Bilateral Exchange</h1>
              <p className="lede">
                Run a Phase 1.b case, watch enforcement logs stream in, and inspect the
                retrieved information without leaving the browser.
              </p>
            </div>
          </header>

          <section className="grid grid-top">
            <div className="panel hero-card">
              <p className="hero-label">API Base</p>
              <p className="hero-value">{apiBase}</p>
              <p className="hero-label">Latest Event</p>
              <p className="hero-value">
                {lastLog ? `${lastLog.level} · ${lastLog.message}` : "Waiting for activity"}
              </p>
            </div>
            <div className="panel run">
              <div className="panel-header">
                <h2>Run a Case</h2>
                <span className="pill">Phase 1.b</span>
              </div>
              <label className="field">
                <span>Case ID</span>
                <select
                  value={selectedCase}
                  onChange={(event) => setSelectedCase(event.target.value)}
                >
                  {CASE_OPTIONS.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.id} · {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <div className="context-block">
                <p className="context-label">FI-A Request Context</p>
                <p className="hint">{selectedMeta?.summary}</p>
              </div>
              <button className="run-button" onClick={runCase} disabled={running}>
                {running ? "Running..." : "Run Selected Case"}
              </button>
              {runResult ? (
                <div className="result">
                  <p className="result-label">FI-A Outcome</p>
                  <p className="result-value">
                    {runResult.status.toUpperCase()} · {runResult.match_type ?? "-"}
                  </p>
                  {runResult.error_message ? (
                    <>
                      <p className="result-sub-label">Responder Block / Error</p>
                      <p className="result-error">{runResult.error_message}</p>
                    </>
                  ) : (
                    <>
                      <p className="result-sub-label">FI-B Response Summary</p>
                      <p className="result-summary">{runResult.summary}</p>
                    </>
                  )}
                </div>
              ) : null}
              {error ? <p className="error">{error}</p> : null}
            </div>
          </section>

          <section className="grid">
            <div className="panel graph graph-wide">
              <div className="panel-header">
                <h2>Institutions</h2>
                <span className="pill">A2A</span>
              </div>
              <div className="graph-surface">
                <div className="graph-node">
                  <div className="node-icon">A</div>
                  <div>
                    <p className="node-title">FI-A Requestor</p>
                    <p className="node-subtitle">Request + Enforcement</p>
                  </div>
                </div>
                <div className="graph-link">
                  <div className="graph-line" />
                  <span className="graph-label">A2A : SLIM</span>
                </div>
                <div className="graph-node">
                  <div className="node-icon">B</div>
                  <div>
                    <p className="node-title">FI-B Responder</p>
                    <p className="node-subtitle">Evaluation + Response</p>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section className="grid grid-double">
            <div className="panel logs">
              <div className="panel-header">
                <h2>Live Enforcement Log</h2>
                <span className="pill">Polled</span>
              </div>
              <div className="log-view">
                {logs.length === 0 ? (
                  <p className="empty">No log activity yet. Start a case to view events.</p>
                ) : (
                  logs.map((entry) => (
                    <div key={`${entry.id}-${entry.timestamp}`} className="log-entry">
                      <span className="log-time">{formatTimestamp(entry.timestamp)}</span>
                      <span className={`log-level log-${entry.level.toLowerCase()}`}>
                        {entry.level}
                      </span>
                      <span className="log-message">{entry.message}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
            <div className="panel retrieved">
              <div className="panel-header">
                <h2>Retrieved Information</h2>
                <span className="pill">FI-A Store</span>
              </div>
              <div className="table">
                <div className="table-row table-head">
                  <span>Case ID</span>
                  <span>Match</span>
                  <span>Summary</span>
                  <span>Received</span>
                </div>
                {retrieved.length === 0 ? (
                  <div className="empty">No retrieved information yet.</div>
                ) : (
                  retrieved.map((record, index) => (
                    <div key={`${record.case_id}-${index}`} className="table-row">
                      <span>{record.case_id}</span>
                      <span>{record.match_type}</span>
                      <span className="summary">{record.summary}</span>
                      <span>{formatTimestamp(record.received_at)}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </section>
        </main>
      </div>
    </div>
  );
}
