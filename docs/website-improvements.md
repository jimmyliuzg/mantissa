# Website behavior notes

The web app is a static interface. Its Pyodide calculation engine runs in a Web Worker on the user's device. Config imports, projections, and editing stay in the browser.

## Drafts and sharing

Wizard answers and the active plan are saved in session storage. The editor can explicitly remember the current plan in local storage on this device; clearing local drafts removes that remembered plan and the session drafts. Downloads provide a portable JSON plan or cash-flow CSV.

Share links are self-contained. A config link opens a plan for review; an `s2-` snapshot link carries a frozen result, inputs, and run settings. Editing a snapshot starts a new local calculation. The decoder also accepts the older `s1-` snapshot format. Since plan details and results are embedded in the URL, links should be shared deliberately.

## Planning flow and editor

The guided setup has nine steps: age and retirement timing, spouse, savings, income, retirement spending, state, Social Security, risk tolerance, and review. Optional details support account balances and split current and retirement budgets. Users who are already retired can skip the future retirement date path.

In the detailed editor, `surplus_account_id` identifies the destination for excess cash. `savings_order` controls the priority for funding contributions, up to their configured caps. It does not set withdrawal order. These settings are independent. The editor also supports comparing a baseline with the current run, CSV export, and print layout.

California is the only state with modeled state income tax. The interface discloses that other states currently omit state income tax.

## Development checks

Run `npm test` for all Vitest tests. `npm run test:integration` runs the mounted wizard, guided editor, share dialog, and viewer lifecycle tests. These tests use jsdom and do not represent browser automation. Older scripts in `web/scripts/` may refer to earlier UI behavior; do not treat them as current end-to-end checks.
