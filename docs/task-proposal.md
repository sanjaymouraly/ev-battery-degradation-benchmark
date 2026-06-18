# Terminal-Bench-Science task proposal (draft for the expert author)

**Status (2026-10-21):** built and validated independently. Upstream facts
verified from `harbor-framework/terminal-bench-science` CONTRIBUTING.md:
contributions follow Propose → Build → Review; proposals go through the
Task Proposal Form/Board and rubric review *before* implementation is merged;
tasks must come from practicing domain experts; the TB-Science 0.2 PR window
closed **2026-10-05** ("We are accepting pull requests for
Terminal-Bench-Science 0.2 until October 5, 2026"), i.e. before this build.
A `new task` PR must also link an **approved** proposal discussion, which a
static check (`check-task-proposal-link`) verifies. No approval, submission,
or merge eligibility is claimed. `task.toml` author fields are explicit TODO
placeholders — a real battery researcher must own, review, and submit this.

**What is proven (2026-10-21), independent of the submission blocker:**

| Check | Result |
|---|---|
| Harbor 0.24.0 oracle run | mean reward **1.000** (14/14 verifier tests) |
| Harbor 0.24.0 no-op run | mean reward **0.000** |
| Docker separate-verifier gate | oracle **1**, no-op **0** (verifier `--network none`) |
| Local verifier simulation | oracle 1, no-op 0, forged 0, independent alternative solver 1 |
| Upstream-style static checks | 0 failures |
| **Real upstream static checks (23 scripts)** | **22 PASS / 1 FAIL** — only `check-task-slug.sh` (`ev-battery-science-benchmark` = 4 tokens, upstream cap 3). Similarity check: max 22 % vs. 80 % threshold → pass |
| Package test suite | 33 passed, ruff clean |

Evidence: `docs/validation/` (raw Harbor job directories included).

**Known upstream conflicts (both need a human decision, not a code change):**

1. **Folder slug.** The task lives at the mandated path
   `tasks/engineering-sciences/electrical-engineering/ev-battery-science-benchmark/`.
   Upstream's `ci_checks/check-task-slug.sh` allows at most 3 hyphen-separated
   tokens, so this folder name fails that one check out of 23. Every other
   upstream static check passes. Resolving it means either renaming the folder
   (e.g. `ev-battery-benchmark`) or asking upstream to relax the rule for
   this task — the path was fixed by the project brief, so it has been left
   as-is and the failure is reported rather than silently worked around.
2. **Author identity.** `task.toml` carries explicit TODO placeholders for
   name, email, organisation, profile and research experience. Upstream
   requires a named practicing domain expert; fabricating these would make
   the submission dishonest, so they remain visible TODOs.
3. **Proposal + PR window.** A `new task` PR must link an **approved** Task
   Proposal discussion (static check `check-task-proposal-link`), and the
   0.2 PR window closed 2026-10-05. A new proposal round would have to be
   opened first.

- **Problem.** Robust degradation inference and uncertainty-aware SOH
  estimation from irregular, partially corrupted Li-ion cycling experiments:
  reconstruct valid capacity trajectories, flag corruptions with reasons,
  compare five empirical fade models, forecast SOH with calibrated
  intervals, and estimate EOL — then ship the analysis as a reusable solver.
- **Motivation.** Every lifetime claim from a cycling campaign depends on
  this reconstruction; done naively (nameplate normalisation, unscreened
  artefacts, in-sample model picking), EOL errors of tens of percent follow.
- **Domain/data.** Engineering sciences / electrical engineering /
  electrochemical energy storage. Synthetic ground-truth data with fade
  magnitudes calibrated to the CC-BY-4.0 LFP dataset DOI
  10.5281/zenodo.22286450 (no upstream data redistributed; <100 KB in git,
  so no HF hosting needed). The analysis engine is separately validated on
  the real dataset (`docs/real-data-results.md`).
- **Verification.** Separate-verifier grading against known truth
  (Q0, forecasts, EOL, anomaly F1, interval coverage) plus re-execution of
  the submitted solver on held-out data. Outcome-graded; model identity
  deliberately ungraded (families are near-equivalent). Binary reward.
  The verifier drops privileges before running the submitted solver and
  probes at runtime that the private fixtures are unreadable.
- **Why it needs scientific reasoning.** Coupled normalisation/screening/
  selection/extrapolation decisions; each wrong choice fails downstream
  checks. Not generic ETL or a canned fit (see task README Difficulty).
- **Solvable by an expert.** Full contract in `instruction.md`; reference
  solution runs in seconds; expert estimate 3 h; graduated hints provided.
- **Expected agent failure modes.** Using nominal capacity as Q0; deleting
  outliers silently (partition check); fitting before screening; choosing
  by in-sample R² → poor extrapolation; degenerate/unordered intervals;
  hardcoding outputs (held-out re-run fails); non-deterministic bootstrap.
- **Ethics/licensing.** Synthetic data (MIT, generated for this task);
  Zenodo dataset referenced with attribution only. No human/animal data,
  no dual-use concerns; standard canary strings included.
