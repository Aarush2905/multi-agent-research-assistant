import type { RunStatus } from "../api/types";

const STAGES: { key: RunStatus; label: string }[] = [
  { key: "planning", label: "Planning" },
  { key: "discovery", label: "Discovery" },
  { key: "retrieval", label: "Retrieval" },
  { key: "analysis", label: "Analysis" },
  { key: "cross_analysis", label: "Cross-Source Analysis" },
  { key: "synthesis", label: "Synthesis" },
  { key: "validation", label: "Validation" },
  { key: "completed", label: "Completed" },
];

function stageIndex(status: RunStatus): number {
  if (status === "pending") return -1;
  if (status === "awaiting_clarification") return 0;
  if (status === "failed" || status === "cancelled") return STAGES.length;
  return STAGES.findIndex((s) => s.key === status);
}

export function StageProgress({ status }: { status: RunStatus }) {
  const currentIndex = stageIndex(status);
  const isTerminalError = status === "failed" || status === "cancelled";

  return (
    <div className="flex flex-wrap gap-2" data-testid="stage-progress">
      {STAGES.map((stage, index) => {
        const done = currentIndex > index || status === "completed";
        const active = currentIndex === index && status !== "completed";
        return (
          <div
            key={stage.key}
            className={[
              "rounded-full px-3 py-1 text-xs font-medium border transition-colors",
              done
                ? "bg-emerald-600 text-white border-emerald-600"
                : active
                  ? "bg-indigo-600 text-white border-indigo-600 animate-pulse"
                  : "bg-transparent text-slate-500 border-slate-300 dark:border-slate-700",
            ].join(" ")}
          >
            {stage.label}
          </div>
        );
      })}
      {isTerminalError && (
        <div className="rounded-full px-3 py-1 text-xs font-medium border bg-red-600 text-white border-red-600">
          {status === "failed" ? "Failed" : "Cancelled"}
        </div>
      )}
    </div>
  );
}
