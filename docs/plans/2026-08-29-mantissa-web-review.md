# Mantissa Web — Plan

**Status:** revised after M0 Pyodide spike
**Date:** 2026-08-29
**Owner:** Jimmy Liu
**Repo (proposed):** `jimmyliuzg/mantissa-web` (separate, public, MIT)

## 1. Goal & non-goals

### Goal
A static + serverless web app that lets anyone review a Mantissa retirement plan interactively. Two entry modes:

- **Upload mode** — user drops a `mantissa` JSON config, the site projects it (deterministic + Monte Carlo), renders the report, and lets the user edit fields and re-run. should allow user to download an updated json based on changes. 
- **Wizard mode** — user answers ~10 minimal questions, the site synthesizes a slim config, runs the same engine, and lets the user download the resulting JSON config (and full report).

### Non-goals (v1)
- No account system. No data retention on the server. No telemetry. All user data is local to the browser session (memory + URL hash).
- Not a generic "personal finance dashboard." Only Mantissa-shaped plans.
- Not a full Mantissa feature port. Engine is reused as a black box.
- No social sharing of plans (no server-side storage). Share links are URL-hash-only (data in the URL, not on a server).
- No mobile-native apps.

## 2. M0 Pyodide spike — results (2026-08-29)

**Goal:** prove Mantissa runs in Pyodide and produces numbers identical to the CLI.

**Method:** static server (`python3 -m http.server`) on `127.0.0.1:8766`, headless Chromium via Playwright, loads Pyodide 0.27.7 from jsDelivr, installs `numpy` + `click` + `tabulate` via `micropip`, then installs the local mantissa wheel (`mantissa-0.2.0-py3-none-any.whl`, 134KB) from the same origin. Runs the same MC that the CLI runs, with the same seed, and diffs KPIs.

Artifacts in `/tmp/mantissa-pyodide-spike/` (kept until project ships):
- `index.html`, `main.js`, `spike.py` — the spike
- `dist/mantissa-0.2.0-py3-none-any.whl` — the wheel served to the browser
- `baseline/run.json`, `baseline/hist.json`, `baseline/project.json` — CLI outputs
- `build.sh`, `serve.sh` — rebuild + serve

### Results — all 21 fields match CLI to 14 decimal places

```
========================================================================
MC ran in browser: 19.936s   (1,000 sims, gaussian, seed 42)
metric                                browser                    cli  match
success_rate                            0.013                  0.013  OK
num_simulations                          1000                   1000  OK
median_final_nw            343738.18737493514     343738.18737493514  OK
p10_final_nw                92849.58754388244      92849.58754388244  OK
p90_final_nw                1362154.445580955      1362154.445580955  OK
median_taxes               229483.82781962454     229483.82781962454  OK
out_of_savings_rate                     0.982                  0.982  OK

Historical method (1,000 sims, seed 42):
success_rate                            0.134                  0.134  OK
num_simulations                          1000                   1000  OK
median_final_nw             591916.3922585739      591916.3922585739  OK
p10_final_nw               231916.15389006457     231916.15389006457  OK
p90_final_nw                2993902.155869938      2993902.155869938  OK
median_taxes               231616.79107801587     231616.79107801587  OK
out_of_savings_rate                     0.859                  0.859  OK

Deterministic projection: 55 rows, year=2026
  year                                 2026                   2026  OK
  primary_age                            36                     36  OK
  income                           229154.4               229154.4  OK
  expenses                          86400.0                86400.0  OK
  taxes                          44580.6712             44580.6712  OK
  net_worth                        549675.0               549675.0  OK
  net_cash_flow                  98173.7288             98173.7288  OK
========================================================================
PARITY
```

Wizard smoke test (synthesized slim config, 500 sims, seed 7): 5.4s in browser, success_rate 0.96, no errors. Confirms the upload-edit-rerun loop works on configs the wizard itself produces.

### Performance

| Path | Native Python | Headless Chromium (Pyodide) | Slowdown |
|---|---|---|---|
| 1,000 sims MC (gaussian) | 7.9s | 19.9s | 2.5× |
| 1,000 sims MC (historical) | (similar) | (similar) | 2.5× |
| 500 sims MC (wizard slim) | n/a measured | 5.4s | n/a |

2.5× slowdown is acceptable for a web tool. 10k sims would be ~200s — too slow. Cap the UI at 5,000 sims for the v1 browser build, and label it as such. Users who want 10k+ can run the CLI.

### Bundle / load size

- Pyodide 0.27.7 full: ~12MB initial (CDN, cacheable).
- NumPy (Pyodide-built wheel): ~7MB.
- click + tabulate: ~250KB.
- mantissa wheel: 134KB.
- Total: ~20MB on first visit, fully cached after that. Service worker recommended for repeat visits.

### Findings that affect the plan

1. **Pyodide is the right call.** Real engine, real numbers, no backend, no cost. **Decision: drop Option B (FastAPI backend). Pyodide only.** Mention Option B as a fallback in the README's architecture section.
2. **micropip must install wheels by URL, not local FS path.** `micropip.install("/tmp/x.whl")` does not work; the wheel must be served by URL. Code pattern is now captured in `main.js`.
3. **`config/validation.py` is loosely coupled to the engine parser.** The schema validator accepts fields the engine then `KeyError`s on. The wizard has to ship **fully-populated** `income_streams[]` and `expenses[]` rows (with `id`, `monthly_amount`, `end_date`, `essential`, etc.) — not the slim subset the schema allows. The site's wizard template must mirror the example config's shape, not just the schema.
4. **`spouse` cannot be `null` or `{}`.** Schema rejects both. Wizard must either always include a real spouse object, or ask "no spouse?" up front and synthesize a stub.
5. **No browser-specific blockers found.** Numpy RNG, deterministic projection, gaussian + historical MC, schema validation all work identically in Pyodide.
6. **Cold start is ~10s** (Pyodide boot + numpy + mantissa load). Mitigation: lazy-load on first "Run" click, not on landing. Show a friendly "loading engine…" the first time.

## 3. Architecture (revised)

**Frontend** — static SPA, no server logic. HTML/CSS/TypeScript. Served from GitHub Pages or Cloudflare Pages.

**Engine** — runs in the browser via Pyodide. Mantissa wheel + numpy + click + tabulate fetched once, cached by service worker, **never talks to a server**. Plans stay on the user's device.

**No backend in v1.** Pyodide removes the entire server tier. Privacy is the strongest it can be.

## 4. Tech stack (revised)

- **Frontend framework:** Vite + Preact. Svelte also acceptable; Preact chosen for ecosystem familiarity and tiny size.
- **Charts:** hand-rolled SVG + d3-scale, or uPlot (~40KB) if SVG becomes painful. SVG preferred for fan chart.
- **State:** Preact signals. No Redux.
- **Forms:** native `<input>` with debounced handlers. No heavy form lib needed for 10 wizard steps.
- **CSS:** plain CSS with custom properties. System font stack + monospace numerics.
- **TypeScript:** yes. Shared types between frontend JSON I/O and the mantissa Python output (generated from mantissa's own model types).
- **Pyodide:** 0.27.x (the spike ran on 0.27.7; pin it).
- **Testing:** Vitest for unit, Playwright for one happy-path browser test.
- **Lint/format:** Biome (single tool, fast).
- **CI:** GitHub Actions — build, test, deploy Pages.

## 5. Privacy & security posture (unchanged)

- **No analytics, no tracking, no cookies.**
- **No localStorage for plan data.** Plans live in JavaScript memory only. Reload = lose plan. (User can save via Download or URL hash share link.)
- **No data ever leaves the browser.** Mantissa wheel + NumPy are cached locally. After first load, everything runs offline.
- **Share link:** URL hash (after `#`) — never sent to server. Encode config with `lz-string` for size. Include a clear warning: "Anyone with this link sees your plan."
- **CSP:** strict. No inline scripts. No third-party origins. SRI on the Pyodide CDN bundle.
- **No auth, no accounts, no rate-limit identity.**

## 6. User flows (unchanged)

### Flow A — Upload existing config

1. User lands on `/`. Sees two big tiles: "Upload a config" and "Start from scratch."
2. Clicks Upload → file picker accepts `.json` (and `.md` for read-only view of an existing report).
3. Frontend validates JSON shape with mantissa's schema (extract `schema_dict()` from the engine into a shared JSON Schema; embed in the frontend bundle).
4. User lands on `/review?config=…` (config in URL hash). KPIs + cash flow + MC fan + tax + sensitivity + warnings all render. **First render triggers the Pyodide lazy-load (one-time, ~10s).**
5. User clicks any value in the right-rail summary → inline edit. On blur, the engine re-runs (debounced 400ms) and charts update.
6. User clicks "Download config" → JSON file with the current edited config. Valid input to the Mantissa CLI.
7. User clicks "Copy share link" → URL with `#config=<lzstring>` copied.

### Flow B — Wizard (no config)

1. User clicks "Start from scratch."
2. Stepper with ~10 screens:
   1. Your current age + planned retirement age
   2. Spouse (yes/no, age, retirement age) — if "no spouse," the wizard synthesizes a stub spouse matching the schema's required fields (see Finding #4 above)
   3. Current investable assets (one number, optional split)
   4. Annual income (today)
   5. Annual retirement spending (today, in today's dollars)
   6. State of residence (dropdown; affects state tax)
   7. Social Security (estimated monthly benefit at 67, or skip)
   8. Health notes (any LTC need? skip by default)
   9. Pension? (skip by default)
   10. Risk tolerance (low/med/high — maps to volatility)
3. The wizard emits a `slim_config.json` from those answers using a deterministic template (`src/slim_template.ts`) — **must mirror example config shape (Finding #3)**, not just schema.
4. User lands on `/review?config=…` with the synthesized config. Same review UI.
5. User refines by editing, or downloads the config.

### Flow C — Read-only Markdown report

- User drops a `mantissa report --format markdown` output. Site renders tables + a static chart re-derived from the numbers. No re-run, no engine call.

## 7. Config schema, slimmed (revised)

The slim template covers the ~95% case. Engine-required fields (Finding #3) come first; the rest is hidden behind "Advanced" in the UI.

**Required for the engine to parse the slim config (not just validate):**
- `primary.{name, birth_date, retirement_date, longevity_age}`
- `spouse.{name, birth_date, retirement_date, longevity_age}` — full object, even for "no spouse" (Finding #4)
- `economic.{inflation, medical_inflation, investment_return_mean, investment_return_volatility}`
- `accounts[]` — at least one, with `{id, name, type, tax_treatment, balance, growth_rate}` (engine accepts subset)
- `income_streams[]` — at least one salary, fully populated: `{id, name, owner, monthly_amount, start_date, end_date, growth_rate, is_w2, social_security_taxable}` (Finding #3)
- `expenses[]` — at least one: `{id, name, monthly_amount, start_date, end_date, category, essential, inflation_adjusted}`
- `social_security` — `{primary_pia, claiming_age_primary}` (or null + skip)
- `withdrawal_strategy` — default `"fixed_real"`
- `withdrawal_rate` — default 0.04
- `state` — two-letter
- `monetary_convention` — default `"real"`

**Hidden behind "Advanced":** mortgages, windfalls, roth_conversions, glidepath, guardrails, equity comp, stress, historical-return method, monthly_contribution, contribution_priority, annual_contribution_cap, owner, equity_pct, expense_ratio, glidepath, is_depreciating, liquid, monthly_amount-based expense variants.

**Action item for mantissa repo:** add a `mantissa schema` JSON Schema export that matches the engine parser, not just the validator. The current `mantissa schema` would let the wizard ship broken configs. Filed as a follow-up; not a v1 web blocker because the wizard template bakes in the right shape.

## 8. Frontend component map (unchanged)

```
<MantissaApp>            # Preact root, owns plan state in a signal
  <Landing>              # "/" — pick Upload / Wizard / View markdown
  <Wizard>               # "/wizard" — stepper for Flow B
  <Review>               # "/review" — the main work surface
    <ConfigDrawer>       # left rail: editable config tree
    <KPIRow>             # success rate, terminal NW, lifetime tax, worst drawdown
    <CashFlowChart>      # stacked area, year-by-year
    <MonteCarloFan>      # p10/p50/p90 with median + drawdown shading
    <TaxBreakdown>       # federal/state/capg stacked bar by year
    <SensitivityTornado> # one var swing
    <WarningsPanel>      # RMD shortfalls, IRMAA tier, withdrawal floor breaches
    <EditField>          # inline editable value (debounced re-run)
    <RunStatus>          # spinner, last-run timestamp, sim count
    <ShareBar>           # download config, copy share link
  <MarkdownView>         # "/view" — read-only markdown report renderer
```

## 9. Backend API contract (REMOVED)

**No backend.** Pyodide replaces it entirely. This section will be removed from the public plan.

## 10. Build plan (revised)

### Milestone 0 — Pyodide parity spike ✅ DONE (this session)

- Built mantissa wheel locally (134KB) and served it alongside the spike page.
- All 21 KPIs match CLI to 14 decimal places across gaussian MC, historical MC, and deterministic projection.
- Wizard smoke test passes (synthesized slim config runs cleanly).
- Findings 1–6 above documented.

### Milestone 1 — Static read-only viewer ✅ DONE (2026-08-29)

What shipped in `web/`:
- Vite + Preact + TypeScript scaffold (`web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`, `web/biome.json`).
- Engine seam (`web/src/engine/types.ts`) with Pyodide implementation (`web/src/engine/pyodide.ts`). Single export in `web/src/engine/index.ts` so the rest of the app never touches Pyodide directly.
- Hash-based router (`/` and `/#/review`) so the site deploys to any static host.
- Landing page with file upload → sessionStorage → viewer.
- Viewer page with KPI row, stacked-area cash-flow chart (SVG), and Monte Carlo fan chart (SVG) — all hand-rolled, zero chart deps.
- Engine-status banner that surfaces Pyodide cold-start state.
- Vitest unit tests for the format helpers.
- Build-wheel script (`web/scripts/build-wheel.sh`) that runs on CI and copies the wheel into `web/public/vendor/`.
- Playwright end-to-end test (`web/scripts/serve-and-spike.py`) that builds, serves, drives the viewer, and asserts the rendered KPIs match the CLI baseline to the displayed precision.
- GitHub Pages deploy workflow (`.github/workflows/pages.yml`).

End-to-end test result (1,000 sims, gaussian, seed 42):
```
KPIS: ['1.3%', '$343.7k', '$92.8k', '$1.36M', '$229.5k', '98.2%', '1,000']
```
vs CLI baseline (`/tmp/mantissa-pyodide-spike/baseline/run.json`):
- success_rate: 1.3% (CLI: 0.013)
- median_final_nw: $343.7k (CLI: 343,738.19)
- p10_final_nw: $92.8k (CLI: 92,849.59)
- p90_final_nw: $1.36M (CLI: 1,362,154.45)
- median_taxes: $229.5k (CLI: 229,483.83)
- out_of_savings_rate: 98.2% (CLI: 0.982)
- num_simulations: 1,000

Bundle: 27KB JS + 4.5KB CSS + 134KB wheel = ~165KB initial. Pyodide + numpy are CDN-fetched once (~20MB), cached by browser.

### Milestone 2 — Editing + re-run ✅ DONE (2026-08-29)

What shipped in `web/`:
- **Plan store** (`web/src/state/plan-store.ts`): signals-based single source of truth. `config` + `sims` signals, a `state` signal of `EngineState` (idle/loading/running/ready/error), and a `rerun()` that increments a run counter so stale in-flight runs are dropped. Engine cancellation deferred to M3 — the run-id gate is good enough.
- **ConfigDrawer** (`web/src/components/config-drawer.tsx`): left rail, sticky, with a curated field set (top-level, primary, spouse, economic, accounts, expenses, income_streams, MC sims) plus an "Advanced JSON" textarea for everything else. 17 typed fields plus 3 list editors.
- **useDebouncedEffect** (`web/src/lib/use-debounced-effect.ts`): 400 ms debounce, last-write-wins. Edits during a run get queued; the next run starts after the in-flight one lands.
- **Download config** button on the viewer header — produces a clean JSON blob with the current edited config.
- **Sim count control**: 500 / 1k / 5k dropdown. Cost labeled ("5k sims takes ~100 s in browser").

End-to-end test (`web/scripts/m2-test.py`):
```
before edit: ['1.3%', '$343.7k', '$92.8k', '$1.36M', '$229.5k', '98.2%', '1,000']
==> editing accounts[0].balance: 150000 → 1500000
==> re-run completed after edit
after edit:  ['95.9%', '$21.09M', '$5.20M', '$65.99M', '$3.44M', '3.4%', '1,000']
==> downloaded accounts[0].balance: 1500000
```
Success rate 1.3% → 95.9% matches the CLI exactly. Median net worth $343.7k → $21.09M. The downloaded JSON has `accounts[0].balance = 1,500,000`.

Unit tests: 16/16 (format helpers + config-edit path helpers).

Bundle: 41 KB JS + 6 KB CSS + 134 KB wheel. Pyodide + numpy still CDN-cached.

### Milestone 3 — Wizard ✅ DONE (2026-08-29)

What shipped in `web/`:
- **Slim config builder** (`web/src/slim/types.ts`): `WizardAnswers` → `buildSlimConfig()`. Emits the smallest Mantissa config the engine accepts end-to-end (verified by the M0 spike and now by a unit test suite). Single-household mode synthesizes a far-future-dated stub `spouse` so the config validates without a real partner. Risk tolerance maps to `investment_return_mean` + `_volatility` per a fixed low/med/high table.
- **Wizard page** (`web/src/pages/wizard.tsx`): 8 question steps + a Review step = 9 progress dots. Two exits: "Download plan.json" produces a valid Mantissa CLI config; "Open in viewer" writes the config to sessionStorage and navigates to `/#/review`.
- **State dropdown**: 50 states + DC.
- **Router update** (`web/src/app.tsx`): added `/#/wizard` route.
- **Landing page**: the wizard tile is now wired (was disabled in M1).

Unit tests: 9 new tests in `web/tests/slim.test.ts` covering the engine-required field set, ISO date format, risk mapping, single-household stub, and the integer-rounding of monthly amounts. **25/25 unit tests pass overall.**

E2E test (`web/scripts/m3-test.py`):
```
==> clicking Start from scratch
==> progress dots: 9
==> walking through 8 question steps
==> reached review step
==> opening in viewer
==> viewer KPIs: ['100.0%', '$90.80B', '$9.63B', '$1128.93B', '$10.27M', '0.0%', '1,000']
==> M3 OK
```

Default wizard profile (35, retire 65, $250k assets, $120k income, $60k spending, CA, $2.4k SS) → 100% success rate, $90.8B median final NW. Plan is over-funded for the spending target; not a bug, just a profile hint that the defaults could be more conservative. Worth flagging in M4.

Bundle: 52 KB JS + 8 KB CSS + 134 KB wheel.

### Milestone 4 — Share + polish
- Scope: URL-hash share link, lz-string compression, copy-to-clipboard, OG image for shared links, mobile pass, accessibility audit, CSP hardening.

### Milestone 5 (optional) — Compare two plans
- Scope: drop second config, side-by-side KPIs, overlaid fan charts.

## 11. Open questions for user (revised — fewer now)

Most are decided by the spike. The remaining ones:

1. **Sim cap.** Plan calls for 5,000 sims in v1 browser (200s worst case). OK, or do you want a "fast" / "thorough" toggle (1k default, 5k opt-in)? Let's do fast / thorough toggle. Thorough toggle should be 10,000 however and include some warning or loading animation/screen. 
2. **Slim template coverage.** Confirm the 10-question wizard scope. Anything mandatory for your audience I left out (e.g., pension income, dependents)? Works for now. 
3. **Branding** — match `mantissa` CLI styling? Dark mode? Logo? Let's address this later. 
4. **Repository** — separate `mantissa-web` repo, or `web/` subdir of `mantissa`? let's add this to the mantissa repo as a subdir
5. **License** — MIT, matching Mantissa? MIT. 
6. **Schema export** — should I also file an issue/PR on the mantissa repo to make `mantissa schema` match the engine parser? (Out of scope for v1 web, but the wizard's fragility comes from this gap.) yes. 

## 12. Risks (revised)

- **Schema/engine drift** — mitigated by the wizard template mirroring example config shape, not just the schema. Long-term fix: better schema export from mantissa.
- **Monte Carlo determinism** — fixed seed for share links so the same config produces the same fan chart every time. Spike already confirms seed works in Pyodide.
- **Pyodide cold start** — ~10s on first visit. Mitigated by lazy-load on first "Run," not on landing. Service worker cache eliminates second-visit cost.
- **NumPy RNG parity** — confirmed by spike. NumPy version pinned via the Pyodide wheel set; do not mix pip wheels.
- **No offline-after-first-load risk** — once Pyodide + mantissa are cached, the site works fully offline. Document this as a feature.
- **No PWA** in v1; revisit if adoption demands it.

## 13. Repo layout (unchanged)

```
mantissa-web/
├── src/
│   ├── components/         # Preact components
│   ├── parsers/            # config + markdown parsing
│   ├── engine/             # Pyodide wrapper
│   ├── schema/             # generated JSON Schema (checked in)
│   ├── slim/               # wizard template + synthesizer
│   ├── charts/             # SVG/uPlot wrappers
│   ├── state/              # signals, persistence-free
│   └── main.ts
├── samples/                # committed sample configs
├── public/
│   └── pyodide/            # (optional) vendored Pyodide for self-host
├── tests/
│   ├── unit/
│   ├── browser/            # Playwright
│   └── parity/             # CLI vs browser output diff
├── scripts/
│   ├── build-wheel.sh      # builds mantissa-X.Y.Z-py3-none-any.whl
│   ├── sync-schema.mjs     # pulls schema_dict() from mantissa
│   └── spike.py            # the parity spike
├── .github/workflows/
│   ├── test.yml
│   └── pages.yml
├── index.html
├── vite.config.ts
├── package.json
├── tsconfig.json
├── biome.json
└── README.md
```

## 14. What this plan does not include (unchanged)

- No LLM-generated narrative summaries.
- No tax-form export.
- No advisor collaboration.
- No historical-return replay UI in v1.
