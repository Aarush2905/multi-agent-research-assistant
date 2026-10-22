import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createResearchRun } from "../api/client";
import { QueryInput } from "../components/QueryInput";

export function NewResearchPage() {
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(question: string) {
    setSubmitting(true);
    setError(null);
    try {
      const { run_id } = await createResearchRun(question);
      navigate(`/runs/${run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start research run.");
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-16">
      <div>
        <h1 className="text-3xl font-semibold">Multi-Agent Research Assistant</h1>
        <p className="mt-2 text-slate-500">
          Ask a research question. The assistant will decompose it, search academic
          and web sources, analyze and compare evidence, and produce a cited report.
        </p>
      </div>
      <QueryInput onSubmit={handleSubmit} disabled={submitting} />
      {error && <p className="text-sm text-red-500">{error}</p>}
    </div>
  );
}
