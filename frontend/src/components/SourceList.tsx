import { useState } from "react";
import type { Source } from "../api/types";

const PROVIDER_LABELS: Record<string, string> = {
  arxiv: "arXiv",
  semantic_scholar: "Semantic Scholar",
  pubmed: "PubMed",
  patents: "Patents (web)",
  web: "Web",
};

const RETRIEVAL_COLORS: Record<string, string> = {
  success: "text-emerald-600 dark:text-emerald-400",
  partial: "text-amber-600 dark:text-amber-400",
  not_attempted: "text-slate-400",
};

function getFailureExplanation(status: string, error?: string | null): string {
  if (error && error.trim()) {
    return error;
  }
  switch (status) {
    case "failed_paywall":
      return "Paywall or access restricted by publisher (HTTP 403)";
    case "failed_timeout":
      return "Connection timed out waiting for server response";
    case "failed_unsupported_format":
      return "Document format could not be parsed as text or PDF";
    case "failed_not_found":
      return "Document not found or blocked by host server";
    default:
      return "Could not retrieve full document from host";
  }
}

export function SourceList({ sources }: { sources: Source[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (sources.length === 0) {
    return <p className="text-sm text-slate-500">No sources discovered yet.</p>;
  }

  return (
    <ul className="flex flex-col gap-2">
      {sources.map((source) => {
        const isOpen = expanded === source.source_id;
        const retrievalColor =
          RETRIEVAL_COLORS[source.retrieval_status] ?? "text-red-500";
        const isFailed =
          source.retrieval_status !== "success" &&
          source.retrieval_status !== "not_attempted";
        return (
          <li
            key={source.source_id}
            className="rounded-lg border border-slate-200 bg-white p-3 text-sm shadow-sm dark:border-slate-800 dark:bg-slate-900"
          >
            <button
              className="flex w-full flex-col items-start gap-1 text-left"
              onClick={() => setExpanded(isOpen ? null : source.source_id)}
            >
              <span className="font-medium">{source.title}</span>
              <span className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span className="rounded bg-slate-100 px-2 py-0.5 dark:bg-slate-800">
                  {PROVIDER_LABELS[source.provider] ?? source.provider}
                </span>
                {source.publication_year && <span>{source.publication_year}</span>}
                <span className={retrievalColor}>{source.retrieval_status.replace(/_/g, " ")}</span>
                {isFailed && (
                  <span className="font-normal text-rose-500 dark:text-rose-400">
                    • {getFailureExplanation(source.retrieval_status, source.retrieval_error)}
                  </span>
                )}
              </span>
            </button>
            {isOpen && (
              <div className="mt-2 border-t border-slate-100 pt-2 text-xs text-slate-600 dark:border-slate-800 dark:text-slate-400">
                {isFailed && (
                  <div className="mb-2 rounded border border-rose-200 bg-rose-50/80 p-2 text-xs text-rose-800 dark:border-rose-900/50 dark:bg-rose-950/40 dark:text-rose-300">
                    <span className="font-semibold">Retrieval Notice: </span>
                    {getFailureExplanation(source.retrieval_status, source.retrieval_error)}
                  </div>
                )}
                {source.authors.length > 0 && <p>Authors: {source.authors.join(", ")}</p>}
                {source.abstract && <p className="mt-1">{source.abstract}</p>}
                {source.url && (
                  <a
                    className="mt-1 inline-block text-indigo-600 hover:underline dark:text-indigo-400"
                    href={source.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    View source
                  </a>
                )}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
