# Harbor 0.24.0 run evidence

These are the **unmodified output directories** produced by two real
`harbor run` invocations against this task on 2026-10-21 (Harbor 0.24.0,
Docker backend). Nothing here was edited or re-generated.

| Directory | Command | Mean reward | `verifier/reward.txt` |
|---|---|---:|---|
| `oracle-run/` | `harbor run -p <task> -a oracle` | **1.000** | `1` |
| `noop-run/` | `harbor run -p <task> -a nop` | **0.000** | `0` |

Each directory contains the job-level `result.json` / `job.log` / `config.json`
and one trial directory with:

* `verifier/reward.txt` — the binary reward written by `/tests/test.sh`
* `verifier/ctrf.json` — the CTRF test report
  (oracle: `{"tests": 14, "passed": 14, "failed": 0}`)
* `verifier/test-stdout.txt` — the verifier's pytest output
* `artifacts/root/results/` — the artifacts the agent phase produced
  (empty for the no-op run)
* `agent/oracle.txt` — the oracle agent's transcript

Job ids: oracle `c5bf202a-1d21-4df1-b0c4-7188321af657`,
no-op `6ab05128-8e7e-416f-823d-79e1f9c82213`.

The no-op run's CTRF report is large because every missing artifact produces a
full pytest error report — that is the expected shape for a failed trial
(`{"tests": 14, "passed": 1, "failed": 13}`).

Both job directories were also accepted by the upstream
`ci_checks/check-verifier-output.py` ("binary reward, well-formed ctrf.json").

Reproduce with:

```bash
pip install "harbor==0.24.0"
harbor run -p tasks/engineering-sciences/electrical-engineering/ev-battery-science-benchmark -a oracle
harbor run -p tasks/engineering-sciences/electrical-engineering/ev-battery-science-benchmark -a nop
```
