import { useEffect } from "preact/hooks";

/**
 * useEffect that only fires after `delay` ms of stable inputs. Edits
 * during the delay window reset the timer, so the effect only runs once
 * after the user stops typing.
 */
export function useDebouncedEffect(
  fn: () => void | (() => void),
  deps: ReadonlyArray<unknown>,
  delay: number,
): void {
  useEffect(() => {
    const t = setTimeout(fn, delay);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, delay]);
}
