"""Sentinel CLI: ``sentinel validate`` and ``sentinel history``.

``validate <dataset>`` loads the dataset and policy YAML, runs the
orchestrator, saves the run and prints a summary (with incident priority
for failed rules). ``history <dataset>`` lists recent runs.

Exit codes for ``validate`` respect non-blocking rules:

    0 - nothing failed or warned
    1 - a warning, but no blocking failure
    2 - a blocking rule failed
"""

from __future__ import annotations

import uuid

import typer

from sentinel.cli.bootstrap import build_context
from sentinel.cli.resolution import resolve_dataset, resolve_policy
from sentinel.datasources import get_data_source
from sentinel.domain import Incident, QualityEvent, Status, ValidationRun
from sentinel.orchestration import ValidationOrchestrator
from sentinel.persistence.failure_history import DuckDBFailureHistorySource
from sentinel.persistence.history import DuckDBHistoricalMetricsSource
from sentinel.persistence.reader import RunSummary, list_recent_runs
from sentinel.persistence.writer import persist_validation_run

app = typer.Typer(help="Sentinel: configurable data quality validation.")


def _has_blocking_failure(events: tuple[QualityEvent, ...]) -> bool:
    return any(event.blocking and event.status is Status.FAIL for event in events)


def _has_warning(events: tuple[QualityEvent, ...]) -> bool:
    return any(event.status is Status.WARN for event in events)


def _exit_code(run: ValidationRun) -> int:
    """Map a run to the exit code described in the module docstring."""
    if _has_blocking_failure(run.quality_events):
        return 2
    if _has_warning(run.quality_events):
        return 1
    return 0


def _headline(exit_code: int) -> str:
    return {0: "PASS", 1: "WARN", 2: "FAIL (blocking)"}[exit_code]


def _format_value(value: float) -> str:
    """Format a metric value to 4 significant figures."""
    return f"{value:.4g}"


def _incident_for(run: ValidationRun, event: QualityEvent) -> Incident | None:
    """Find the Incident for ``event``, if it has one.

    Not a zip(): incidents only exist for non-PASS events.
    """
    for incident in run.incidents:
        if incident.quality_event is event:
            return incident
    return None


def _print_summary(run: ValidationRun, run_id: uuid.UUID, exit_code: int) -> None:
    typer.echo(f"Dataset: {run.dataset.name}")
    typer.echo(f"Run ID:  {run_id}")
    typer.echo(f"Result:  {_headline(exit_code)}")
    typer.echo("")
    for event in run.quality_events:
        mark = "✓" if event.status is Status.PASS else "✗"
        actual = _format_value(event.actual)
        typer.echo(f"  {mark} {event.rule_name}  actual={actual}  expected: {event.expected}")
        incident = _incident_for(run, event)
        if incident is not None:
            top_reason = incident.reasons[0] if incident.reasons else ""
            typer.echo(
                f"      priority={incident.priority.value.upper()} "
                f"score={incident.score}  {top_reason}"
            )


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

    history_source = DuckDBHistoricalMetricsSource(context.conn)
    failure_history_source = DuckDBFailureHistorySource(context.conn)
    orchestrator = ValidationOrchestrator(
        history_source=history_source,
        failure_history_source=failure_history_source,
    )
    run = orchestrator.run(resolved_dataset, policy, source)
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
