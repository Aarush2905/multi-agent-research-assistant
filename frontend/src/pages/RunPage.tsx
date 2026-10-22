import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { cancelResearchRun, clarifyResearchRun, exportReportPdfUrl, getResearchRun } from "../api/client";
import { ClarificationPrompt } from "../components/ClarificationPrompt";
import { FollowUpChat } from "../components/FollowUpChat";
import { ReportView } from "../components/ReportView";
import { SourceList } from "../components/SourceList";
import { StageProgress } from "../components/StageProgress";
import type { RunStatusResponse } from "../api/types";

const ACTIVE_STATUSES = new Set([
  "pending",
  "planning",
  "discovery",
  "retrieval",
  "analysis",
  "cross_analysis",
  "synthesis",
  "validation",
]);

export function RunPage() {
  const { runId } = useParams<{ runId: string }>();
  const [run, setRun] = useState<RunStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    if (!runId) return;
    try {
      const data = await getResearchRun(runId);
      setRun(data);
      if (!ACTIVE_STATUSES.has(data.status) && intervalRef.current) {
        window.clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load run status.");
    }
  }, [runId]);

  useEffect(() => {
    refresh();
    intervalRef.current = window.setInterval(refresh, 2500);
    return () => {
      if (intervalRef.current) window.clearInterval(intervalRef.current);
    };
  }, [refresh]);

  if (error) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 text-sm text-red-500">
        {error}. <Link to="/" className="underline">Start a new run</Link>.
      </div>
    );
  }

  if (!run) {
    return <div className="mx-auto max-w-2xl px-4 py-16 text-sm text-slate-500">Loading...</div>;
  }

  const state = run.state ?? {};
  const sources = state.sources ?? [];
  const report = state.report;
  const errors = state.errors ?? [];
  const providerErrors = state.provider_errors ?? {};

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-8 px-4 py-10">
      <header className="flex flex-col gap-3">
        <Link to="/" className="text-sm text-indigo-600 hover:underline dark:text-indigo-400">
          New research
        </Link>
        <h1 className="text-xl font-semibold">{run.research_question}</h1>
        <StageProgress status={run.status} />
        {ACTIVE_STATUSES.has(run.status) && (
          <button
            className="self-start text-xs text-red-500 hover:underline"
            onClick={() => runId && cancelResearchRun(runId).then(refresh)}
          >
            Cancel run
          </button>
        )}
      </header>

      {run.status === "awaiting_clarification" && (
        <ClarificationPrompt
          plan={state.plan}
          onSubmit={(response) => {
            if (!runId) return;
            clarifyResearchRun(runId, response).then(refresh);
          }}
        />
      )}

      {errors.length > 0 && (
        <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
          {errors.map((e, i) => (
            <p key={i}>{e}</p>
          ))}
        </div>
      )}

      {Object.keys(providerErrors).length > 0 && (
        <details className="text-xs text-slate-500">
          <summary className="cursor-pointer">Provider notices ({Object.keys(providerErrors).length})</summary>
          <ul className="mt-1 list-inside list-disc">
            {Object.entries(providerErrors).map(([provider, message]) => (
              <li key={provider}>
                <span className="font-medium">{provider}:</span> {message}
              </li>
            ))}
          </ul>
        </details>
      )}

      {sources.length > 0 && !report && (
        <section>
          <h2 className="mb-2 text-lg font-medium">Discovered Sources ({sources.length})</h2>
          <SourceList sources={sources} />
        </section>
      )}

      {report && (
        <>
          <div className="flex justify-end">
            <a
              href={exportReportPdfUrl(run.run_id)}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-900"
            >
              Export PDF
            </a>
          </div>
          <ReportView report={report} sources={sources} />
          <section>
            <h2 className="mb-2 text-lg font-medium">Sources ({sources.length})</h2>
            <SourceList sources={sources} />
          </section>
          <FollowUpChat runId={run.run_id} />
        </>
      )}
    </div>
  );
}
