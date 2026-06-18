#!/bin/bash
set -euo pipefail
evbatt inspect data/example_synthetic.csv
evbatt analyze data/example_synthetic.csv --metadata examples/metadata.json -o results/example
ls results/example
