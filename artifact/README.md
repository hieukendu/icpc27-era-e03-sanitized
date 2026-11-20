# E03: evidence scope in AI code explanations

A retrospective/exploratory replication package for **What Evidence Supports an AI Code Explanation? A Retrospective Study of Slot and Sentence Scope**.

The evaluated checker is frozen v6.1. The release is E03-scoped-v1. All semantic audits and corrected-slot annotations are tentative assistant coding; independent human labels and participant outcomes are pending. Historical raw codes `true` and `false` mean **slot-supported** and **candidate refutation**, respectively. They do not assert sentence truth.

## Offline replay

Use Python 3.13, install the pinned packages once, and run from this directory:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
make replay PY=.venv/bin/python
```

If dependencies are already installed in `python3`, the single replay command is `make replay`. The build also requires pdflatex, bibtex, IEEEtran, pgfplots, pdfinfo and pdftotext. The observed system toolchain is recorded in `results/revision/build_environment.json`; visual review additionally uses pdftoppm. No R installation is needed to replay the frozen simulation results.

Replay verifies hashes of required frozen observations/cache inputs and corrected annotations, regenerates original and revised analyses, runs the engine/revision tests, renders manuscript fragments, and compiles `../manuscript/main.pdf`. Missing or changed inputs fail closed. Python network connections are disabled during analysis; no model endpoint is called. Generated probes and repository functions are not executed. This is replay of frozen observations, not a new explanation experiment or rerun of the original sandboxed probes.

## Actual mixed-model simulation

R and the package versions listed in `results/revision/simulation/R-packages.csv` are required. Install the pinned package set with `Rscript src/install_simulation.R`. Then run:

```sh
make simulate
```

This fits 60,000 crossed logistic models and can take substantial CPU time. It resumes completed scenario files. Use `make simulate SIM_CORES=4` to reduce concurrency. Cached scenario results are reused only with their matching simulation source hash. `make replay` incorporates the resulting table into the paper.

## What to inspect

- [Semantic contract](docs/semantic-contract.md) and [detailed rules](docs/detailed-rules.md).
- [Revision methods](docs/revision-methods.md): denominators, audit interval, policies, prevalence assumptions and annotation limitations.
- [Badge-study protocol](docs/badge-study.md): primary contrast, allocation, model and simulation assumptions.
- `results/revision/planted_ledger.csv`: all 151 frozen pairs, both sides, exclusions and audit status.
- `results/revision/planted_cohorts.csv`: unconditional, label-error-filtered and historical selected cohorts.
- `results/revision/claim_contracts.jsonl`: original explanations, extracted text, normalized target, scope and evidence.
- `data/revision/corrected_slots.jsonl`: 246 frozen assistant-corrected S/D target inputs, including 40 unrepresentable twins; not gold labels.
- `results/revision/slot_ablation.jsonl` and `slot_transitions.csv`: aligned before/after outcomes.
- `results/revision/audit_frame.csv`: exact 315-item sampling frame and 40 selected IDs.
- `results/revision/risk_coverage.csv`: scope risk, nominal-label risk and explicit unknown-label bounds.
- `results/revision/prevalence_sensitivity.csv`: nominal refutation precision for five assumed prevalences, with function-bootstrap uncertainty.
- `results/revision/simulation/`: fitted-model simulation summaries, allocation and replicate results; no human observations.
- `results/revision/bibliography_metadata.json`: publisher/preprint metadata retrieval evidence.

## Historical compatibility

`results/v1` through `results/v6`, original JSONL outcome codes, and the original audits are retained. The old `heldout` keys describe the v1 development split; current-engine results are retrospective. Legacy scripts/comments and `results/RUNLOG.md` retain their original terminology for provenance. The active contract and manuscript supersede those interpretations.

`make run` remains the original pipeline and may generate model calls when cache entries are absent. It is not the offline replay command. `ATTEST_OFFLINE=1` makes model-cache misses fail without calling a backend. `make data`, `make warm` and `make select` are historical data-generation commands and are outside frozen revision replay.

`python tests/test_engine.py` includes intentionally documented limitations; zero failing regression cases does not imply soundness. Current-version results are not an untouched test set.

## Release and third-party provenance

The release-root manifest hashes every packaged file. Verify it with `python verify_release.py` before replay. Source snapshots and cached model responses are included for reproducibility; repository clones, credentials, local editor state, bytecode, build directories and unrelated projects are excluded. Upstream source excerpts retain their repository/commit provenance and licenses under `licenses/`. Twemoji icons are CC-BY 4.0; see `../manuscript/figures/icons/SOURCES.md`.
