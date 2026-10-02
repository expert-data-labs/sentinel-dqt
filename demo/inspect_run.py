"""Read-only drill-down into one validation run's incidents -- the parts the
dashboard doesn't show (run id, all five score components, all five reasons,
threshold details). Opens the store with read_only=True; never writes.

    SENTINEL_DB_PATH=demo/demo.duckdb uv run python demo/inspect_run.py            # latest run
    SENTINEL_DB_PATH=demo/demo.duckdb uv run python demo/inspect_run.py <run-id>   # a specific run

Stop the dashboard first: DuckDB allows only one process to hold the file.
"""

from __future__ import annotations

import json
import os
import sys

import duckdb

conn = duckdb.connect(os.environ.get("SENTINEL_DB_PATH", "sentinel.duckdb"), read_only=True)

if len(sys.argv) > 1:
    run_id = sys.argv[1]
else:
    row = conn.execute("SELECT id FROM validation_runs ORDER BY started_at DESC LIMIT 1").fetchone()
    if row is None:
        sys.exit("No validation runs in this store yet.")
    run_id = str(row[0])

run = conn.execute(
    "SELECT dataset_id, started_at, status, policy_version FROM validation_runs WHERE id = ?",
    [run_id],
).fetchone()
if run is None:
    sys.exit(f"No run with id {run_id}")
print(
    f"Run {run_id}\n"
    f"  dataset={run[0]}  started={run[1]}  status={run[2].upper()}  policy={run[3]}\n"
)

events = conn.execute(
    """
    SELECT m.metric_name, m.value, qe.status, qe.expected, qe.severity, qe.blocking,
           qe.details, i.priority, i.score, i.components, i.reasons
    FROM quality_events qe
    JOIN metrics m ON m.id = qe.metric_id
    LEFT JOIN incidents i ON i.quality_event_id = qe.id
    WHERE qe.validation_run_id = ?
    ORDER BY i.score DESC NULLS LAST, m.metric_name
    """,
    [run_id],
).fetchall()

for row in events:
    name, value, status, expected, severity, blocking, details, prio, score, comps, reasons = row
    print(f"- {name}: {status.upper()}  value={value:.4g}  expected: {expected}")
    print(f"    severity={severity}  blocking={blocking}  threshold={details}")
    if prio is not None:
        print(f"    INCIDENT priority={prio.upper()} score={score}")
        print(f"    components={json.loads(comps)}")
        for reason in json.loads(reasons):
            print(f"      · {reason}")
    print()
