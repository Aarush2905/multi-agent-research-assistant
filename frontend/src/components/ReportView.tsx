import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { ResearchReport, Source } from "../api/types";

function CitationBadges({
  citationIds,
  onSelect,
}: {
  citationIds: string[];
  onSelect: (citationId: string) => void;
}) {
  if (citationIds.length === 0) return null;
  return (
    <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
      {citationIds.map((cid) => (
        <button
          key={cid}
          onClick={() => onSelect(cid)}
          className="rounded bg-indigo-100 px-1.5 py-0.5 text-[11px] font-medium text-indigo-700 hover:bg-indigo-200 dark:bg-indigo-900 dark:text-indigo-300"
        >
          {cid}
        </button>
      ))}
    </span>
  );
}

export function ReportView({ report, sources }: { report: ResearchReport; sources: Source[] }) {
  const [selectedCitation, setSelectedCitation] = useState<string | null>(null);

  const sourceByCitation = useMemo(() => {
    const sourcesById = new Map(sources.map((s) => [s.source_id, s]));
    const map = new Map<string, Source | undefined>();
    for (const c of report.citations) {
      map.set(c.citation_id, sourcesById.get(c.source_id));
    }
    return map;
  }, [report.citations, sources]);

  const selectedSource = selectedCitation ? sourceByCitation.get(selectedCitation) : null;

  return (
    <article className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold">{report.title}</h1>
        <p className="mt-1 text-sm text-slate-500">{report.research_question}</p>
      </header>

      <section>
        <h2 className="text-lg font-medium">Executive Summary</h2>
        <div className="mt-1 text-sm leading-relaxed text-slate-700 dark:text-slate-300">
          <ReactMarkdown>{report.executive_summary.text}</ReactMarkdown>
        </div>
        <CitationBadges
          citationIds={report.executive_summary.citation_ids}
          onSelect={setSelectedCitation}
        />
      </section>

      {report.sections.map((section) => (
        <section key={section.heading}>
          <h2 className="text-lg font-medium">{section.heading}</h2>
          <div className="mt-1 text-sm leading-relaxed text-slate-700 dark:text-slate-300">
            <ReactMarkdown>{section.body}</ReactMarkdown>
          </div>
          <CitationBadges citationIds={section.citation_ids} onSelect={setSelectedCitation} />
        </section>
      ))}

      {report.limitations.length > 0 && (
        <section>
          <h2 className="text-lg font-medium">Limitations</h2>
          <ul className="mt-1 list-inside list-disc text-sm text-slate-600 dark:text-slate-400">
            {report.limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      )}

      {report.research_gaps.length > 0 && (
        <section>
          <h2 className="text-lg font-medium">Research Gaps</h2>
          <ul className="mt-1 list-inside list-disc text-sm text-slate-600 dark:text-slate-400">
            {report.research_gaps.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      )}

      {report.citations.length > 0 && (
        <section>
          <h2 className="text-lg font-medium">References</h2>
          <ol className="mt-1 flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-400">
            {report.citations.map((c) => {
              const source = sourceByCitation.get(c.citation_id);
              return (
                <li key={c.citation_id}>
                  <span className="font-mono text-xs text-indigo-600 dark:text-indigo-400">
                    [{c.citation_id}]
                  </span>{" "}
                  {source ? (
                    <a href={source.url ?? undefined} target="_blank" rel="noreferrer" className="hover:underline">
                      {source.title}
                    </a>
                  ) : (
                    c.source_id
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      )}

      {selectedSource && (
        <div
          className="fixed inset-0 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setSelectedCitation(null)}
        >
          <div
            className="max-w-md rounded-lg bg-white p-4 shadow-xl dark:bg-slate-900"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="font-medium">{selectedSource.title}</h3>
            {selectedSource.authors.length > 0 && (
              <p className="mt-1 text-xs text-slate-500">{selectedSource.authors.join(", ")}</p>
            )}
            {selectedSource.abstract && (
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">{selectedSource.abstract}</p>
            )}
            {selectedSource.url && (
              <a
                href={selectedSource.url}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-block text-sm text-indigo-600 hover:underline dark:text-indigo-400"
              >
                Open source
              </a>
            )}
            <button
              className="mt-3 block text-xs text-slate-400 hover:text-slate-600"
              onClick={() => setSelectedCitation(null)}
            >
              Close
            </button>
          </div>
        </div>
      )}
    </article>
  );
}
