import { useState } from "react";
import type { ResearchPlan } from "../api/types";

export function ClarificationPrompt({
  plan,
  onSubmit,
}: {
  plan: ResearchPlan | null | undefined;
  onSubmit: (response: string) => void;
}) {
  const [value, setValue] = useState("");

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-700 dark:bg-amber-950">
      <p className="text-sm font-medium text-amber-900 dark:text-amber-200">
        {plan?.clarification_question ??
          "Could you clarify your research question before we proceed?"}
      </p>
      <form
        className="mt-3 flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (value.trim()) onSubmit(value.trim());
        }}
      >
        <input
          className="flex-1 rounded-md border border-amber-300 bg-white px-3 py-2 text-sm focus:outline-none dark:border-amber-700 dark:bg-slate-900"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Your answer..."
        />
        <button
          type="submit"
          disabled={!value.trim()}
          className="rounded-md bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-500 disabled:opacity-50"
        >
          Continue
        </button>
      </form>
    </div>
  );
}
