#!/bin/bash
# Container-level validation replicating Harbor separate-verifier semantics.
# Use when `harbor run` is unavailable (e.g. host kernel lacks
# CONFIG_NFT_FIB_INET for Harbor's egress-control sidecar). This script:
#   1. builds environment/ and tests/ images,
#   2. agent phase: runs solution/solve.sh (oracle) or nothing (nop)
#      in the environment container,
#   3. copies ONLY the artifacts declared in task.toml,
#   4. verifier phase: fresh tests-image container with --network none,
#      artifacts injected at /root/results, runs /tests/test.sh,
#   5. asserts the binary reward in /logs/verifier/reward.txt.
# Usage: scripts/validate_task_docker.sh [oracle|nop|both]
set -uo pipefail
cd "$(dirname "$0")/.."
TASK=tasks/engineering-sciences/electrical-engineering/ev-battery-science-benchmark
ARTIFACTS="analysis.json clean_cycles.csv anomalies.csv model_comparison.csv uncertainty.csv predictions.csv solve.py"

run_scenario() {
  local mode=$1
  local work="validation_runs/docker-$mode"
  rm -rf "$work" && mkdir -p "$work/results"
  echo "== [$mode] agent phase =="
  docker rm -f "evbatt-agent-$mode" >/dev/null 2>&1 || true
  if [ "$mode" = "oracle" ]; then
    docker run --name "evbatt-agent-$mode" -v "$PWD/$TASK/solution:/solution:ro" \
      evbatt-task-env bash /solution/solve.sh || { echo "agent phase FAILED"; return 1; }
  else
    docker run --name "evbatt-agent-$mode" evbatt-task-env true
  fi
  for f in $ARTIFACTS; do
    docker cp "evbatt-agent-$mode:/root/results/$f" "$work/results/$f" 2>/dev/null || \
      echo "  (artifact $f absent)"
  done
  docker rm -f "evbatt-agent-$mode" >/dev/null
  echo "== [$mode] verifier phase (--network none) =="
  docker rm -f "evbatt-verifier-$mode" >/dev/null 2>&1 || true
  docker run --name "evbatt-verifier-$mode" --network none \
    -v "$PWD/$work/results:/root/results" \
    evbatt-task-tests bash /tests/test.sh > "$work/verifier.log" 2>&1 || true
  local reward
  reward=$(docker cp "evbatt-verifier-$mode:/logs/verifier/reward.txt" - 2>/dev/null | tar -xO 2>/dev/null || echo "MISSING")
  docker rm -f "evbatt-verifier-$mode" >/dev/null
  echo "$reward" > "$work/reward.txt"
  echo "[$mode] reward=$reward  (log: $work/verifier.log)"
  tail -3 "$work/verifier.log"
}

docker build -t evbatt-task-env "$TASK/environment" >/dev/null || exit 1
docker build -t evbatt-task-tests "$TASK/tests" >/dev/null || exit 1
case "${1:-both}" in
  oracle) run_scenario oracle ;;
  nop)    run_scenario nop ;;
  both)   run_scenario oracle; run_scenario nop
          echo "oracle=$(cat validation_runs/docker-oracle/reward.txt) nop=$(cat validation_runs/docker-nop/reward.txt)" ;;
esac
