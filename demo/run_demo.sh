#!/usr/bin/env bash
# Demo: four daily loads of a CRITICAL `payments` dataset through
# `sentinel validate`, using only demo/ datasets and policies and its own
# `sentinel_demo` database. Needs Postgres running: `docker compose up -d`.
#
# Run from anywhere:   bash demo/run_demo.sh
# Then the dashboard:  bash demo/run_demo.sh dashboard
set -uo pipefail
cd "$(dirname "$0")/.."            # repo root: config_reference paths resolve from here

export SENTINEL_DATABASE_URL="${SENTINEL_DEMO_DATABASE_URL:-postgresql://sentinel:sentinel@localhost:5432/sentinel_demo}"
export SENTINEL_DATASETS_DIR=demo/datasets
export SENTINEL_POLICIES_DIR=demo/policies

if [[ "${1:-}" == "dashboard" ]]; then
  exec uv run streamlit run dashboard/app.py
fi

uv run python demo/reset_db.py || exit 1        # fresh demo database every time

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
echo "Deep-dive a run:  SENTINEL_DATABASE_URL=$SENTINEL_DATABASE_URL uv run python demo/inspect_run.py [run-id]"
