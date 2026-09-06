"""Sentinel's command-line interface: ``sentinel validate`` and
``sentinel history``.

``sentinel validate <dataset>`` resolves a Dataset and Policy from the
filesystem convention (cli/resolution.py — both named ``<dataset>.yaml``
in their own directory), builds the DataSource its Dataset declares
(``source_type``), runs the existing ValidationOrchestrator unchanged,
persists the outcome, and prints a summary.

``sentinel history <dataset> [--limit N]`` reads that persisted history
back via persistence/reader.py — a thin projection (timestamp, status,
which rules failed), not a reconstructed domain object graph; see
docs/architecture/0003-milestone-2-architecture.md Part 5.

The process exit code is a deliberately separate, blocking-aware
judgment on top of ``ValidationRun.status`` — not a mirror of it. FR-12
lets a policy mark a rule non-blocking: a FAIL there should still show up
in the printed summary (nothing about a rule's true status is hidden),
but it shouldn't fail a pipeline step that shells out to this command.
See docs/architecture/0003-milestone-2-architecture.md Part 8 for the
three-way split this implements:

    exit 0 — no blocking event FAILs, and nothing WARNs.
    exit 1 — something WARNs, but no blocking event FAILs.
    exit 2 — a blocking event FAILs.

This is the question Milestone 0 explicitly left open when it added
``QualityEvent.blocking`` without folding it into ``ValidationRun.status``
("that's a Milestone 2 CLI decision") — resolved here, at the one layer
that actually needs to turn a judgment into a process outcome.
"""

from __future__ import annotations

import uuid

import typer

from sentinel.cli.bootstrap import build_context
from sentinel.cli.resolution import resolve_dataset, resolve_policy
from sentinel.datasources import get_data_source
from sentinel.domain import QualityEvent, Status, ValidationRun
from sentinel.orchestration import ValidationOrchestrator
from sentinel.persistence.reader import RunSummary, list_recent_runs
from sentinel.persistence.writer import persist_validation_run

app = typer.Typer(help="Sentinel: configurable data quality validation.")


def _has_blocking_failure(events: tuple[QualityEvent, ...]) -> bool:
    return any(event.blocking and event.status is Status.FAIL for event in events)


def _has_warning(events: tuple[QualityEvent, ...]) -> bool:
    return any(event.status is Status.WARN for event in events)


def _exit_code(run: ValidationRun) -> int:
    """The blocking-aware verdict described in this module's docstring."""
    if _has_blocking_failure(run.quality_events):
        return 2
    if _has_warning(run.quality_events):
        return 1
    return 0


def _headline(exit_code: int) -> str:
    return {0: "PASS", 1: "WARN", 2: "FAIL (blocking)"}[exit_code]


def _format_value(value: float) -> str:
    """Trim a metric's float value to a readable number of significant
    figures for the terminal — 0.083333333333 is noise a person reading
    a summary doesn't need."""
    return f"{value:.4g}"


def _print_summary(run: ValidationRun, run_id: uuid.UUID, exit_code: int) -> None:
    typer.echo(f"Dataset: {run.dataset.name}")
    typer.echo(f"Run ID:  {run_id}")
    typer.echo(f"Result:  {_headline(exit_code)}")
    typer.echo("")
    for event in run.quality_events:
        mark = "✓" if event.status is Status.PASS else "✗"
        actual = _format_value(event.actual)
        typer.echo(f"  {mark} {event.rule_name}  actual={actual}  expected: {event.expected}")


_DATASET_HELP = (
    "Dataset name, e.g. 'orders' (matches datasets/<name>.yaml and "
    "policies/<name>.yaml)."
)


@app.command()
def validate(
    dataset: str = typer.Argument(..., help=_DATASET_HELP),
) -> None:
    """Run DATASET's policy, persist the result, and report a summary."""
    context = build_context()

    resolved_dataset = resolve_dataset(dataset)
    policy = resolve_policy(dataset)
    source = get_data_source(resolved_dataset.source_type, resolved_dataset.config_reference)

    run = ValidationOrchestrator().run(resolved_dataset, policy, source)
    run_id = persist_validation_run(context.conn, run)

    exit_code = _exit_code(run)
    _print_summary(run, run_id, exit_code)
    raise typer.Exit(code=exit_code)


_LIMIT_HELP = "Maximum number of recent runs to show."


def _print_history(dataset: str, summaries: list[RunSummary]) -> None:
    if not summaries:
        typer.echo(f"No recorded runs for dataset {dataset!r}.")
        return

    typer.echo(f"Dataset: {dataset}")
    typer.echo("")
    for summary in summaries:
        timestamp = summary.started_at.isoformat(timespec="seconds")
        line = f"  {timestamp}  {summary.status.value.upper():<4}  run={summary.run_id}"
        if summary.failed_rules:
            line += f"  failed: {', '.join(summary.failed_rules)}"
        typer.echo(line)


@app.command()
def history(
    dataset: str = typer.Argument(..., help=_DATASET_HELP),
    limit: int = typer.Option(10, "--limit", help=_LIMIT_HELP),
) -> None:
    """Show DATASET's most recent recorded validation runs."""
    context = build_context()
    summaries = list_recent_runs(context.conn, dataset, limit)
    _print_history(dataset, summaries)


if __name__ == "__main__":
    app()
