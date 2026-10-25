import { h, render } from "preact";
import { describe, expect, it } from "vitest";
import { ModelWarnings } from "../src/components/model-warnings";

describe("model limitations", () => {
  it("shows engine messages as text", () => {
    const host = document.createElement("div");
    render(
      h(ModelWarnings, {
        warnings: [
          {
            year: null,
            category: "model",
            severity: "warning",
            message: "Missing cost_basis for <brokerage>",
          },
        ],
      }),
      host,
    );
    expect(host.querySelector('[aria-label="Model limitations"]')).not.toBeNull();
    expect(host.querySelector("li")?.textContent).toBe("Missing cost_basis for <brokerage>");
    expect(host.querySelector("brokerage")).toBeNull();
  });

  it("does not add an empty panel to older snapshots", () => {
    const host = document.createElement("div");
    render(h(ModelWarnings, { warnings: [] }), host);
    expect(host.children.length).toBe(0);
  });
});
