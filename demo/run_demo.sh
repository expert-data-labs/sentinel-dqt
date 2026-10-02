#!/usr/bin/env bash
# Phase 3 demo: simulates four daily loads of a CRITICAL `payments` dataset
# through the real `sentinel validate` pipeline, into an ISOLATED store.
# Touches nothing outside demo/: its own DB, datasets dir, and policies dir.
#
# Run from anywhere:   bash demo/run_demo.sh
# Then the dashboard:  bash demo/run_demo.sh dashboard
set -uo pipefail
cd "$(dirname "$0")/.."            # repo root: config_reference paths resolve from here

export SENTINEL_DB_PATH=demo/demo.duckdb
export SENTINEL_DATASETS_DIR=demo/datasets
export SENTINEL_POLICIES_DIR=demo/policies

if [[ "${1:-}" == "dashboard" ]]; then
  exec uv run streamlit run dashboard/app.py
fi

rm -f demo/demo.duckdb demo/demo.duckdb.wal   # fresh demo store every time

for snap in 1_clean 2_bad_load 3_still_bad 4_partial_fix; do
  echo
  echo "================ load: $snap ================"
  cp "demo/data/snapshots/$snap.csv" demo/data/payments.csv
  uv run sentinel validate payments
  echo "(exit code: $?  -- 0 pass, 1 warn, 2 blocking fail)"
  sleep 1                                     # distinct timestamps per run
done

echo
echo "================ sentinel history payments ================"
uv run sentinel history payments
echo
echo "Next:  bash demo/run_demo.sh dashboard"
echo "Deep-dive a run:  SENTINEL_DB_PATH=demo/demo.duckdb uv run python demo/inspect_run.py [run-id]"
