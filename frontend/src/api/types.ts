export type RunStatus =
  | "pending"
  | "planning"
  | "awaiting_clarification"
  | "discovery"
  | "retrieval"
  | "analysis"
  | "cross_analysis"
  | "synthesis"
  | "validation"
  | "completed"
  | "failed"
  | "cancelled";

export interface SubQuestion {
  text: string;
  rationale: string;
}

export interface SearchQuery {
  text: string;
  target_sources: string[];
  originating_subquestion: string | null;
}

export interface ResearchPlan {
  research_question: string;
  primary_domain: string;
  secondary_domains: string[];
  sub_questions: SubQuestion[];
  search_queries: SearchQuery[];
  selected_sources: string[];
  document_types: string[];
  planning_warnings: string[];
  needs_clarification: boolean;
  clarification_question: string | null;
}

export interface Source {
  source_id: string;
  title: string;
  authors: string[];
  abstract: string | null;
  publication_year: number | null;
  provider: string;
  url: string | null;
  doi: string | null;
  venue: string | null;
  document_type: string;
  publication_status: string;
  is_open_access: boolean | null;
  retrieval_status: string;
  retrieval_error?: string | null;
  relevance_score: number;
}

export interface Citation {
  citation_id: string;
  source_id: string;
}

export interface ReportSection {
  heading: string;
  body: string;
  citation_ids: string[];
}

export interface ReportSummary {
  text: string;
  citation_ids: string[];
}

export interface ResearchReport {
  title: string;
  research_question: string;
  executive_summary: ReportSummary;
  sections: ReportSection[];
  limitations: string[];
  research_gaps: string[];
  citations: Citation[];
  generated_at: string;
}

export interface RunState {
  plan?: ResearchPlan | null;
  sources?: Source[];
  report?: ResearchReport | null;
  errors?: string[];
  stage_warnings?: Record<string, string[]>;
  provider_errors?: Record<string, string>;
  validation_attempts?: number;
}

export interface RunStatusResponse {
  run_id: string;
  status: RunStatus;
  research_question: string;
  state: RunState;
}

export interface FollowUpExchange {
  question: string;
  answer: string;
  citation_ids: string[];
  created_at: string;
}
