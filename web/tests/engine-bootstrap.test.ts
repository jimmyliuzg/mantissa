import { afterEach, describe, expect, it, vi } from "vitest";

function fakeRuntime(install = vi.fn().mockResolvedValue(undefined)) {
  return {
    globals: { set: vi.fn() },
    runPythonAsync: vi.fn().mockResolvedValue(undefined),
    toPy: vi.fn(),
    pyimport: vi.fn().mockReturnValue({ install }),
    FS: { writeFile: vi.fn() },
    loadPackage: vi.fn().mockResolvedValue(undefined),
  };
}

afterEach(() => {
  delete window.loadPyodide;
  vi.resetModules();
});

describe("engine bootstrap", () => {
  it("stays unready until the wheel and import smoke test finish", async () => {
    let release!: () => void;
    const runtime = fakeRuntime();
    runtime.runPythonAsync.mockReturnValue(
      new Promise<void>((resolve) => {
        release = resolve;
      }),
    );
    window.loadPyodide = vi.fn().mockResolvedValue(runtime);
    const { pyodideEngine } = await import("../src/engine/pyodide");
    const first = pyodideEngine.bootstrap();
    const second = pyodideEngine.bootstrap();
    await vi.waitFor(() => expect(runtime.runPythonAsync).toHaveBeenCalledTimes(1));
    expect(pyodideEngine.isReady()).toBe(false);
    await expect(
      pyodideEngine.run({}, { simulations: 1, method: "gaussian", seed: 42 }),
    ).rejects.toThrow(/not bootstrapped/);
    release();
    await Promise.all([first, second]);
    expect(pyodideEngine.isReady()).toBe(true);
    expect(window.loadPyodide).toHaveBeenCalledTimes(1);
  });

  it("allows retry after a dependency installation fails", async () => {
    const broken = fakeRuntime(vi.fn().mockRejectedValue(new Error("network failed")));
    const good = fakeRuntime();
    window.loadPyodide = vi.fn().mockResolvedValueOnce(broken).mockResolvedValueOnce(good);
    const { pyodideEngine } = await import("../src/engine/pyodide");
    await expect(pyodideEngine.bootstrap()).rejects.toThrow("network failed");
    expect(pyodideEngine.isReady()).toBe(false);
    await pyodideEngine.bootstrap();
    expect(pyodideEngine.isReady()).toBe(true);
    expect(good.runPythonAsync).toHaveBeenCalledTimes(1);
  });
});
