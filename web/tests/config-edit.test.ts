import { describe, expect, it } from "vitest";
import { getPath, setPath } from "../src/lib/config-edit";

describe("setPath / getPath", () => {
  const base = {
    name: "demo",
    economic: { inflation: 0.025, medical_inflation: 0.04 },
    accounts: [{ id: "a", balance: 100 }, { id: "b", balance: 200 }],
  };

  it("reads a top-level key", () => {
    expect(getPath(base, "name")).toBe("demo");
  });

  it("reads a nested key", () => {
    expect(getPath(base, "economic.inflation")).toBe(0.025);
  });

  it("reads an array element by index", () => {
    expect(getPath(base, "accounts.1.balance")).toBe(200);
  });

  it("returns undefined for missing path", () => {
    expect(getPath(base, "economic.nonexistent")).toBeUndefined();
    expect(getPath(base, "accounts.5.balance")).toBeUndefined();
    expect(getPath(null, "anything")).toBeUndefined();
  });

  it("sets a top-level key immutably", () => {
    const next = setPath(base, "name", "renamed");
    expect(next).not.toBe(base);
    expect((next as { name: string }).name).toBe("renamed");
    expect(base.name).toBe("demo"); // original unchanged
  });

  it("sets a nested key immutably", () => {
    const next = setPath(base, "economic.inflation", 0.03);
    expect(next).not.toBe(base);
    expect((next as { economic: { inflation: number } }).economic.inflation).toBe(0.03);
    expect(base.economic.inflation).toBe(0.025);
  });

  it("sets an array element immutably", () => {
    const next = setPath(base, "accounts.0.balance", 999);
    expect(next).not.toBe(base);
    const accounts = (next as { accounts: Array<{ balance: number }> }).accounts;
    expect(accounts[0]?.balance).toBe(999);
    expect(accounts[1]?.balance).toBe(200);
    expect(base.accounts[0]?.balance).toBe(100); // original unchanged
  });

  it("does not mutate the original at any nesting level", () => {
    const next = setPath(base, "accounts.0.balance", 0) as {
      accounts: Array<{ balance: number }>;
    };
    expect(next.accounts).not.toBe(base.accounts);
    expect(next.accounts[0]).not.toBe(base.accounts[0]);
  });

  it("round-trips a numeric value with full precision", () => {
    const next = setPath(base, "economic.inflation", 0.123456789) as {
      economic: { inflation: number };
    };
    expect(getPath(next, "economic.inflation")).toBe(0.123456789);
  });
});
