import { h, render } from "preact";
import { act } from "preact/test-utils";
import { afterEach, expect, it, vi } from "vitest";
vi.mock("../src/pages/viewer", () => ({ Viewer: () => h("h1", {}, "Test plan results") }));
import { App } from "../src/app";

let host: HTMLDivElement | null = null;
afterEach(() => {
  if (host) { act(() => render(null, host!)); host.remove(); host = null; }
  document.querySelector(".skip-link")?.remove();
  window.location.hash = "";
  sessionStorage.clear();
});

it("focuses main content without changing the viewer hash or losing its route", () => {
  window.location.hash = "#/review";
  const skip = document.createElement("a");
  skip.className = "skip-link"; skip.href = "#main-content"; skip.textContent = "Skip to content";
  document.body.append(skip);
  host = document.createElement("div"); document.body.append(host);
  act(() => render(h(App, {}), host!));
  act(() => skip.click());
  expect(window.location.hash).toBe("#/review");
  expect(document.activeElement).toBe(host.querySelector("main"));
  expect(host.textContent).toContain("Test plan results");
});
