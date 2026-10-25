import type { Warning } from "../engine/types";

export function ModelWarnings({ warnings }: { warnings: Warning[] }) {
  if (!warnings?.length) return null;
  return (
    <section class="panel" aria-label="Model limitations">
      <h2>Model limitations</h2>
      <ul>
        {warnings.map((warning, index) => (
          <li key={index}>{warning.message}</li>
        ))}
      </ul>
    </section>
  );
}
