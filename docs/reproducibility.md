# Reproducible Monte Carlo runs

Pass an integer `seed` from `0` through `9,007,199,254,740,991` to
`MonteCarloEngine.run()` to repeat the same Monte Carlo run with the same
scenario, method, volatility, stress level, planner inputs, and model/runtime.
Seeds stay within the exact integer range shared by JSON and JavaScript. A run
without a seed chooses one once and returns it as
`result["run_metadata"]["effective_seed"]`; pass that value back as `seed` to
replay the run.

`run_metadata` records the run settings and model version. When the planner
provides a `config_fingerprint()` method, metadata records its resolved
scenario fingerprint and identifies it as such. The fingerprint is a
reproducibility identifier; raw scenario configuration is not copied into the
metadata. If the planner exposes a rule registry, metadata records published
rule catalog lineage and compact per-year summaries. It omits caller policy
payloads and contribution values.

Historical runs select starting indices from the available S&P 500 annual
return series and wrap cyclically when a simulation outlasts the series. The
metadata records the series year range, the number of available starts, and
the sampled indices so the historical path can be inspected alongside the
effective seed.

The simulation uses local random generators; it does not change Python's or
NumPy's module-level random state. Gaussian returns and stochastic mortality
share the run's seeded NumPy generator. Historical start selection uses a
separate seeded Python generator.

Monte Carlo results aggregate model warnings across runs in
`result["model_warnings"]`, including annual contribution warnings such as
skipped automatic funding.
