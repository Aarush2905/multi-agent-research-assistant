import { useEffect, useState } from "react";
import { askFollowUp, getFollowUps } from "../api/client";
import type { FollowUpExchange } from "../api/types";

export function FollowUpChat({ runId }: { runId: string }) {
  const [exchanges, setExchanges] = useState<FollowUpExchange[]>([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getFollowUps(runId)
      .then(setExchanges)
      .catch(() => undefined);
  }, [runId]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q) return;
    setLoading(true);
    setError(null);
    try {
      const exchange = await askFollowUp(runId, q);
      setExchanges((prev) => [...prev, exchange]);
      setQuestion("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to get an answer.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-lg font-medium">Ask a follow-up question</h2>
      <div className="flex flex-col gap-3">
        {exchanges.map((exchange, i) => (
          <div key={i} className="rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-800">
            <p className="font-medium">{exchange.question}</p>
            <p className="mt-1 text-slate-600 dark:text-slate-400">{exchange.answer}</p>
            {exchange.citation_ids.length > 0 && (
              <p className="mt-1 text-xs text-indigo-600 dark:text-indigo-400">
                Citations: {exchange.citation_ids.join(", ")}
              </p>
            )}
          </div>
        ))}
      </div>
      <form className="flex gap-2" onSubmit={handleSubmit}>
        <input
          className="flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none dark:border-slate-700 dark:bg-slate-900"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask about the evidence already collected..."
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {loading ? "Thinking..." : "Ask"}
        </button>
      </form>
      {error && <p className="text-sm text-red-500">{error}</p>}
    </div>
  );
}
