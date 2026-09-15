import { engine } from "@engine";
import { useEffect, useState } from "preact/hooks";

type Status = "idle" | "loading" | "ready" | "error";

/**
 * Sticky bar that surfaces Pyodide boot state. v1 boots lazily on the
 * first Run; the M0 spike showed ~10s cold start.
 */
export function EngineStatus() {
  const [status, setStatus] = useState<Status>(engine.isReady() ? "ready" : "idle");
  const [err, setErr] = useState<string | null>(null);
  const [ms, setMs] = useState<number | null>(null);

  useEffect(() => {
    if (status !== "idle") return;
    const onFirst = async () => {
      setStatus("loading");
      const t0 = performance.now();
      try {
        await engine.bootstrap();
        setMs(Math.round(performance.now() - t0));
        setStatus("ready");
      } catch (e) {
        setErr(String(e));
        setStatus("error");
      }
    };
    // Kick off on first user interaction OR after 250ms idle.
    let kicked = false;
    const kick = () => {
      if (kicked) return;
      kicked = true;
      void onFirst();
    };
    const evs: (keyof WindowEventMap)[] = ["pointerdown", "keydown"];
    evs.forEach((e) => window.addEventListener(e, kick, { once: true, passive: true }));
    const t = setTimeout(kick, 250);
    return () => {
      clearTimeout(t);
      evs.forEach((e) => window.removeEventListener(e, kick));
    };
  }, [status]);

  if (status === "ready") return null;

  return (
    <div class={`engine-status engine-status--${status}`} role="status" aria-live="polite">
      {status === "loading" && (
        <div class="run-progress-bar" aria-hidden="true">
          <span />
        </div>
      )}
      {status === "idle" && "Engine idle · loads on first run"}
      {status === "loading" && "Loading engine (Pyodide + mantissa)… first run takes ~10 s."}
      {status === "error" && `Engine failed: ${err}`}
    </div>
  );
}
