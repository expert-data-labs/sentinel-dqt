"""Milestone 4's synthetic evaluation framework: deterministic scenarios
(`scenarios.py`) and the runner that scores every registered
ThresholdStrategy against them (`runner.py`), producing
`docs/experiments/milestone-4-results.md`.

See docs/architecture/0005-milestone-4-design.md Part 7 for why this
lives as a small, re-runnable script rather than a notebook, and why it
bypasses Rule/DataSource/the orchestrator/persistence entirely.
"""
