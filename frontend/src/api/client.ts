import type { FollowUpExchange, RunStatusResponse } from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function createResearchRun(researchQuestion: string) {
  return request<{ run_id: string; status: string }>("/api/research", {
    method: "POST",
    body: JSON.stringify({ research_question: researchQuestion }),
  });
}

export function getResearchRun(runId: string) {
  return request<RunStatusResponse>(`/api/research/${runId}`);
}

export function clarifyResearchRun(runId: string, clarificationResponse: string) {
  return request<{ run_id: string; status: string }>(`/api/research/${runId}/clarify`, {
    method: "POST",
    body: JSON.stringify({ clarification_response: clarificationResponse }),
  });
}

export function cancelResearchRun(runId: string) {
  return request<{ run_id: string; status: string }>(`/api/research/${runId}/cancel`, {
    method: "POST",
  });
}

export function askFollowUp(runId: string, question: string) {
  return request<FollowUpExchange>(`/api/research/${runId}/followup`, {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

export function getFollowUps(runId: string) {
  return request<FollowUpExchange[]>(`/api/research/${runId}/followups`);
}

export function getGeminiStatus() {
  return request<{ ok: boolean; message: string }>("/api/gemini/status");
}

export function exportReportPdfUrl(runId: string): string {
  return `${BASE_URL}/api/research/${runId}/export/pdf`;
}
