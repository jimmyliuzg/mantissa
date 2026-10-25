# Mantissa Web

Static browser interface for building and reviewing Mantissa retirement plans. Plan calculations run locally in a Web Worker using Pyodide; plans are not uploaded to a server.

## Develop

```bash
# From the web/ directory
bash scripts/build-wheel.sh
npm install
npm run dev
```

`npm run build` type-checks and builds the static site. `npm run preview` serves the production build locally. `npm test` runs the Vitest suite; `npm run test:integration` runs the mounted wizard, editor, sharing, and viewer lifecycle tests in jsdom. Browser automation scripts under `scripts/` are historical and are not part of the current test commands.

## Current experience

- Start with a nine-step guided setup, including optional details, split current and retirement budgets, spouse details, and an already-retired path. The wizard keeps its draft in session storage.
- Import a JSON plan or open the fictional sample. Edit the plan with guided controls or Advanced JSON; calculations run in a local worker.
- The editor distinguishes `surplus_account_id` (where excess cash goes) from `savings_order` (the priority for funding contributions).
- The review shows projections, simulated outcomes, model warnings, and input readiness. Compare a saved baseline, download cash-flow CSV, or print results.
- Create a link containing either the plan configuration or a frozen full result snapshot. Snapshot links use the `s2-` format; older `s1-` snapshot links remain readable. Shared links contain their plan and results in the URL, so review the contents before sharing.
- The current plan draft lasts for the browser session. You can explicitly opt in to remembering a plan on this device, or clear local drafts from the editor.

California is the only state income tax modeled. Other state selections omit state income tax and are disclosed in the interface.

For the Python command-line tool and configuration reference, see the [Mantissa project](https://github.com/jimmyliuzg/mantissa).
