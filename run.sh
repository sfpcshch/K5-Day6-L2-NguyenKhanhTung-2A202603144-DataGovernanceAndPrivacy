#!/usr/bin/env bash
# One-command reproduce: run PoC offline, evaluate, run tests.
#   ./run.sh            (track from configs/lab.yaml)
#   ./run.sh t11
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-.venv/bin/python}
TRACK=${1:-$($PY -c "from src.common.io import load_config;print(load_config('configs/lab.yaml')['track'])")}
PRED=$($PY -c "from src.metrics.tracks import get_track;print(get_track('$TRACK').pred_file)")
$PY -m src.main --config configs/lab.yaml --track "$TRACK" --output out/poc --run-name poc --offline --seed 42
# Ground truth ships only with the instructor overlay; without it, evaluate against internal validation GT if present.
if compgen -G "fixtures/*/gt" > /dev/null; then
  $PY -m src.evaluate --track "$TRACK" --pred "out/poc/$PRED" --run-name poc --out reports/metrics_poc.json
elif [ -f "reports/internal_gt_t09.csv" ] && [ "$TRACK" = "t09" ]; then
  $PY -m src.evaluate --track "$TRACK" --gt reports/internal_gt_t09.csv --pred "out/poc/$PRED" --run-name poc --out reports/metrics_poc.json
else
  echo "run.sh: fixtures/*/gt not found (instructor overlay not installed) - skipping evaluation" >&2
fi
$PY -m pytest -q
