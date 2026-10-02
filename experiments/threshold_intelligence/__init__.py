"""Milestone 4's synthetic evaluation framework: deterministic scenarios
(`scenarios.py`) and the runner that scores every registered
ThresholdStrategy against them (`runner.py`), producing
`docs/experiments/threshold-strategy-evaluation.md`.

See docs/components/thresholds.md for why this
lives as a small, re-runnable script rather than a notebook, and why it
bypasses Rule/DataSource/the orchestrator/persistence entirely.
"""
