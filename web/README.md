# Mantissa Web

Browser-based interactive viewer for [Mantissa](https://github.com/jimmyliuzg/mantissa) retirement plans.

The site is static + Pyodide. The full Mantissa engine runs in your browser; plans never leave your device. See [`../docs/plans/2026-08-29-mantissa-web-review.md`](../docs/plans/2026-08-29-mantissa-web-review.md) for the full plan.

## Status: M3 (wizard)

What works:
- Drop a Mantissa JSON config, see deterministic projection + Monte Carlo KPIs.
- Edit 17 typed fields (primary, spouse, economic, accounts, expenses, income_streams) plus an Advanced JSON textarea.
- Edits debounce 400 ms then re-run the engine; charts and KPIs update live.
- Sim count control: 500 / 1,000 / 5,000.
- Download the edited config as JSON.

What's next (M3+): 10-question wizard, share links, compare mode.

## Local development

```bash
# 1. Build the mantissa wheel into web/public/vendor/
bash scripts/build-wheel.sh

# 2. Install JS deps
npm install

# 3. Run dev server (http://127.0.0.1:8766)
npm run dev

# 4. Build for production
npm run build
npm run preview
```

## End-to-end test (Playwright)

```bash
# Builds, serves, drives the viewer with Playwright, asserts KPI parity
# against /tmp/mantissa-pyodide-spike/baseline/run.json.
python3 scripts/serve-and-spike.py
```

## Architecture

- **Engine seam:** `src/engine/types.ts` is the contract. `src/engine/pyodide.ts` is the only Pyodide-aware file. To swap engines, add `src/engine/api.ts` and change `src/engine/index.ts`.
- **Routes:** hash-based (`/#/review`) so the site deploys to any static host without SPA-fallback rewrites.
- **No data leaves the browser.** SessionStorage for the in-flight config; nothing in localStorage, no telemetry.

## Deploy

GitHub Pages via `.github/workflows/pages.yml`. Builds the wheel, builds the web, deploys to `https://<owner>.github.io/mantissa-web/`.

## M3 — Wizard

`/#/wizard` walks the user through 8 questions (age/retirement, spouse, assets,
income, spending, state, Social Security, risk tolerance) and emits a slim
config the engine accepts. Two paths out:

- "Open in viewer" hands the config to `/#/review` and runs the engine.
- "Download plan.json" gives a valid Mantissa config to use with the CLI.

The slim builder (`web/src/slim/types.ts`) emits a far-future-dated stub
spouse when the user is single, because the engine parser requires
`spouse` to be a full object (M0 finding #4).
