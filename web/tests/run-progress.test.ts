import { describe, expect, it } from "vitest";
import { labelForState } from "../src/components/run-progress";

describe("labelForState", () => {
  it("labels bootstrap distinctly from a projection run", () => {
    expect(labelForState("loading")).toMatch(/loading/i);
    expect(labelForState("running")).toMatch(/monte carlo/i);
  });
});
