import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StageProgress } from "./StageProgress";

describe("StageProgress", () => {
  it("renders all stage labels", () => {
    render(<StageProgress status="discovery" />);
    expect(screen.getByText("Planning")).toBeInTheDocument();
    expect(screen.getByText("Discovery")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("shows a failed badge when the run failed", () => {
    render(<StageProgress status="failed" />);
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });
});
