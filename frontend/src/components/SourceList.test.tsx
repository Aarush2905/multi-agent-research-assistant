import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SourceList } from "./SourceList";
import type { Source } from "../api/types";

describe("SourceList", () => {
  it("renders failure explanation when retrieval fails", () => {
    const mockSources: Source[] = [
      {
        source_id: "s1",
        title: "Test Paper One",
        authors: ["Author A"],
        abstract: "Abstract content",
        publication_year: 2024,
        provider: "patents",
        url: "https://example.com/paper.pdf",
        doi: null,
        venue: null,
        document_type: "article",
        publication_status: "peer_reviewed",
        is_open_access: true,
        retrieval_status: "failed_not_found",
        retrieval_error: "SSL certificate validation failed on host server",
        relevance_score: 1.0,
      },
    ];

    render(<SourceList sources={mockSources} />);

    // Should display the specific failure explanation inline
    expect(screen.getByText(/SSL certificate validation failed on host server/)).toBeInTheDocument();

    // Clicking to expand should display the Retrieval Notice
    fireEvent.click(screen.getByText("Test Paper One"));
    expect(screen.getByText("Retrieval Notice:")).toBeInTheDocument();
  });
});
