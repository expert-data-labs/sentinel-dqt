"""Sentinel observability dashboard (Streamlit).

Run with:

    uv sync --group dashboard
    uv run streamlit run dashboard/app.py

Three pages, chosen in the top bar:

- Overview: is anything wrong right now? Health counts and every dataset, worst first.
- Incidents: what failed in the time window, and is it new or ongoing?
- Dataset: one dataset's metric trends, runs and incidents.

Display only: all data comes from ObservabilityQueryService. Reads the Postgres
store at SENTINEL_DATABASE_URL, so run ``sentinel validate <dataset>`` a few
times first. Each page render borrows a connection from a shared pool, so many
viewers can use it at once.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import altair as alt
import pandas as pd
import streamlit as st
from psycopg_pool import ConnectionPool

from sentinel.observability.bands import expected_range
from sentinel.observability.queries import ObservabilityQueryService, TimeWindow
from sentinel.observability.views import (
    DatasetHealth,
    DatasetHealthView,
    IncidentHistoryEntry,
    MetricTrendPoint,
    RecurrenceClassification,
)
from sentinel.persistence.engine import StoreConnection, create_pool

_WINDOWS: dict[str, TimeWindow] = {
    "Last 24 hours": TimeWindow.LAST_24H,
    "Last 7 days": TimeWindow.LAST_7D,
    "Last 30 days": TimeWindow.LAST_30D,
}
_DEFAULT_WINDOW = "Last 7 days"

_HEALTH_LABEL = {
    DatasetHealth.CRITICAL: "🔴 critical",
    DatasetHealth.DEGRADED: "🟡 degraded",
    DatasetHealth.UNKNOWN: "⚪ unknown",
    DatasetHealth.HEALTHY: "🟢 healthy",
}
_HEALTH_ORDER = {health: rank for rank, health in enumerate(_HEALTH_LABEL)}  # worst first

_PRIORITY_LABEL = {
    "critical": "🔴 CRITICAL",
    "high": "🟠 HIGH",
    "warning": "🟡 WARNING",
    "info": "🔵 INFO",
}

_STATUS_LABEL = {"pass": "✅ PASS", "warn": "⚠️ WARN", "fail": "❌ FAIL"}

_RECURRENCE_LABEL = {
    RecurrenceClassification.PERSISTENT: "persistent",
    RecurrenceClassification.RECURRING: "recurring",
    RecurrenceClassification.FIRST_OCCURRENCE: "first occurrence",
}
_RECURRENCE_ORDER = {kind: rank for rank, kind in enumerate(_RECURRENCE_LABEL)}

# Session keys
_FOCUS = "focus_dataset"  # the dataset the Dataset page shows
_TABLE_GENERATION = "health_table_generation"  # resets the Overview table's selection


@dataclass(frozen=True)
class _Context:
    """What every page needs: the query service and the selected time window."""

    service: ObservabilityQueryService
    window: TimeWindow
    window_label: str
    as_of: datetime


@st.cache_resource
def _pool() -> ConnectionPool[StoreConnection]:
    """One connection pool per Streamlit server, shared by all sessions."""
    return create_pool(min_size=1, max_size=5)


# -- formatting -------------------------------------------------------------------


def _priority(value: str | None) -> str:
    return _PRIORITY_LABEL.get(value or "", "–")


def _ago(moment: datetime | None, now: datetime) -> str:
    """'5 min ago' style, for metric tiles (tables use DatetimeColumn's 'distance')."""
    if moment is None:
        return "never"
    seconds = max(0.0, (now - moment).total_seconds())
    for unit, size in (("d", 86_400), ("h", 3_600), ("min", 60)):
        if seconds >= size:
            return f"{int(seconds // size)} {unit} ago"
    return "just now"


_WHEN = st.column_config.DatetimeColumn(format="distance", width="small")


def _incident_table(incidents: list[IncidentHistoryEntry], *, show_dataset: bool) -> None:
    rows = [
        {
            "When": i.occurred_at,
            "Dataset": i.dataset_id,
            "Rule": i.rule_name,
            "Priority": _priority(i.priority),
            "Score": i.score,
        }
        for i in incidents
    ]
    st.dataframe(
        rows,
        hide_index=True,
        column_order=[
            c
            for c in ("When", "Dataset", "Rule", "Priority", "Score")
            if show_dataset or c != "Dataset"
        ],
        column_config={
            "When": _WHEN,
            "Score": st.column_config.NumberColumn(format="%.1f", width="small"),
            "Priority": st.column_config.TextColumn(width="small"),
        },
    )


# -- the trend chart ----------------------------------------------------------------


def _trend_chart(points: list[MetricTrendPoint]) -> alt.LayerChart:
    """Measured values over the expected range each run was judged against."""
    rows = []
    for p in points:
        lower, upper = expected_range(p.threshold_details)
        rows.append(
            {
                "computed_at": p.computed_at,
                "value": p.value,
                "lower": lower,
                "upper": upper,
                "result": "not passed" if p.status not in (None, "pass") else "passed",
            }
        )
    # A DataFrame lets Altair serialise timestamps as ISO strings Vega can parse.
    frame = pd.DataFrame(rows, columns=["computed_at", "value", "lower", "upper", "result"])
    frame["computed_at"] = pd.to_datetime(frame["computed_at"], utc=True)
    # Vega's automatic date labels break down on a single timestamp ("…263"),
    # so spell the format out only then.
    x_axis = alt.Axis(format="%d %b %H:%M", labelAngle=0) if len(frame) == 1 else alt.Axis()
    base = alt.Chart(frame).encode(x=alt.X("computed_at:T", title=None, axis=x_axis))
    band = (
        base.transform_filter("datum.lower != null && datum.upper != null")
        .mark_area(opacity=0.25, color="#4c78a8")
        .encode(y=alt.Y("lower:Q", title="value"), y2="upper:Q")
    )
    lower_edge = (
        base.transform_filter("datum.lower != null")
        .mark_line(strokeDash=[4, 3], color="#4c78a8", opacity=0.7)
        .encode(y="lower:Q")
    )
    upper_edge = (
        base.transform_filter("datum.upper != null")
        .mark_line(strokeDash=[4, 3], color="#4c78a8", opacity=0.7)
        .encode(y="upper:Q")
    )
    line = base.mark_line(color="#9ecae9", point=True).encode(y="value:Q")
    # A band needs two runs to have width; with one run, show the allowed range as a bar.
    single_range = (
        base.transform_filter("datum.lower != null && datum.upper != null")
        .mark_rule(color="#4c78a8", strokeWidth=10, opacity=0.35)
        .encode(y="lower:Q", y2="upper:Q")
    )
    failures = (
        base.transform_filter("datum.result == 'not passed'")
        .mark_point(filled=True, size=70, color="#e45756")
        .encode(
            y="value:Q",
            tooltip=[
                alt.Tooltip("computed_at:T", title="run"),
                alt.Tooltip("value:Q", format=",.4~f"),
                alt.Tooltip("lower:Q", format=",.4~f", title="allowed from"),
                alt.Tooltip("upper:Q", format=",.4~f", title="allowed to"),
            ],
        )
    )
    layers = [band, lower_edge, upper_edge, line, failures]
    if len(frame) == 1:
        layers.insert(0, single_range)
    # ",~r" prints plain numbers without trailing zeros: 1,800 / 0.005 / 0.
    return alt.layer(*layers).properties(height=340).configure_axisY(format=",~r")


# -- pages --------------------------------------------------------------------------


def _overview_page(ctx: _Context, open_dataset: Callable[[str], None]) -> None:
    st.title("Overview")
    health = sorted(
        ctx.service.all_datasets_health(),
        key=lambda v: (_HEALTH_ORDER[v.health], v.dataset_name),
    )
    if not health:
        st.info(
            "No validation runs yet. Run `uv run sentinel validate <dataset>` to see data here."
        )
        return

    counts = Counter(v.health for v in health)
    incidents = ctx.service.incident_history(ctx.window, ctx.as_of)
    urgent = sum(1 for i in incidents if i.priority in ("critical", "high"))

    window_help = f"Recorded in the time window ({ctx.window_label.lower()})."
    tiles = st.columns(6)
    tiles[0].metric("Datasets", len(health), border=True)
    tiles[1].metric("Healthy", counts[DatasetHealth.HEALTHY], border=True)
    tiles[2].metric("Degraded", counts[DatasetHealth.DEGRADED], border=True)
    tiles[3].metric("Critical", counts[DatasetHealth.CRITICAL], border=True)
    tiles[4].metric("Incidents", len(incidents), border=True, help=window_help)
    tiles[5].metric("High or critical", urgent, border=True, help=window_help)

    st.subheader("Datasets")
    st.caption(
        "Health reflects each dataset's latest run, whatever the time window. "
        "Worst first; select a row to open it."
    )
    rows = [
        {
            "Dataset": v.dataset_name,
            "Health": _HEALTH_LABEL[v.health],
            "Highest priority": _priority(v.highest_incident_priority),
            "Failed rules": v.failed_rules,
            "Latest validation": v.latest_validation_at,
        }
        for v in health
    ]
    event = st.dataframe(
        rows,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"health_table_{st.session_state.get(_TABLE_GENERATION, 0)}",
        column_config={
            "Dataset": st.column_config.TextColumn(width="medium"),
            "Failed rules": st.column_config.NumberColumn(width="small"),
            "Latest validation": _WHEN,
        },
    )
    if event.selection.rows:
        open_dataset(health[event.selection.rows[0]].dataset_id)


def _incidents_page(ctx: _Context) -> None:
    st.title("Incidents")
    names = {v.dataset_id: v.dataset_name for v in ctx.service.all_datasets_health()}
    filter_col, _ = st.columns([1, 2])
    dataset_id = filter_col.selectbox(
        "Dataset",
        [None, *sorted(names, key=names.__getitem__)],
        format_func=lambda d: "All datasets" if d is None else names[d],
    )

    incidents = ctx.service.incident_history(ctx.window, ctx.as_of, dataset_id=dataset_id)
    failed = ctx.service.failed_rules(ctx.window, ctx.as_of, dataset_id=dataset_id)
    recurring = ctx.service.recurring_failures(ctx.window, ctx.as_of, dataset_id=dataset_id)

    recent_tab, rules_tab, recurring_tab = st.tabs(
        [
            f"Recent incidents ({len(incidents)})",
            f"Failing rules ({len(failed)})",
            f"Recurring ({len(recurring)})",
        ]
    )

    with recent_tab:
        if not incidents:
            st.caption("No incidents in this window.")
        else:
            present = [p for p in _PRIORITY_LABEL if any(i.priority == p for i in incidents)]
            chosen = st.segmented_control(
                "Priority",
                present,
                selection_mode="multi",
                default=present,
                format_func=lambda p: _PRIORITY_LABEL[p],
                key=f"priority_filter_{dataset_id}_{ctx.window.value}",
            )
            _incident_table(
                [i for i in incidents if i.priority in chosen], show_dataset=dataset_id is None
            )

    with rules_tab:
        st.caption("Rules that failed at least once in the window, most failures first.")
        if not failed:
            st.caption("No failed rules in this window.")
        else:
            st.dataframe(
                [
                    {
                        "Dataset": f.dataset_id,
                        "Rule": f.rule_name,
                        "Failures": f.failure_count,
                        "Current priority": _priority(f.current_priority),
                        "Latest failure": f.latest_failure_at,
                    }
                    for f in sorted(failed, key=lambda f: f.failure_count, reverse=True)
                ],
                hide_index=True,
                column_config={"Latest failure": _WHEN},
            )

    with recurring_tab:
        st.caption(
            "**Persistent**: failed more than once and still failing. "
            "**Recurring**: failed more than once, but passed on its latest run. "
            "**First occurrence**: failed once."
        )
        if not recurring:
            st.caption("No failures in this window.")
        else:
            st.dataframe(
                [
                    {
                        "Dataset": r.dataset_id,
                        "Rule": r.rule_name,
                        "Status": _RECURRENCE_LABEL[r.classification],
                        "Failures": r.failure_count,
                        "Last seen": r.last_seen_at,
                    }
                    for r in sorted(
                        recurring,
                        key=lambda r: (_RECURRENCE_ORDER[r.classification], -r.failure_count),
                    )
                ],
                hide_index=True,
                column_config={"Last seen": _WHEN},
            )


def _dataset_page(ctx: _Context) -> None:
    health = {v.dataset_id: v for v in ctx.service.all_datasets_health()}
    if not health:
        st.title("Dataset")
        st.info(
            "No validation runs yet. Run `uv run sentinel validate <dataset>` to see data here."
        )
        return

    ids = sorted(health, key=lambda d: health[d].dataset_name)
    focus = st.session_state.get(_FOCUS)
    title_col, picker_col = st.columns([3, 1], vertical_alignment="bottom")
    dataset_id = picker_col.selectbox(
        "Dataset",
        ids,
        index=ids.index(focus) if focus in ids else 0,
        format_func=lambda d: health[d].dataset_name,
    )
    st.session_state[_FOCUS] = dataset_id
    view: DatasetHealthView = health[dataset_id]
    title_col.title(view.dataset_name)

    tiles = st.columns(4)
    tiles[0].metric("Health", _HEALTH_LABEL[view.health], border=True)
    tiles[1].metric("Latest run", _ago(view.latest_validation_at, ctx.as_of), border=True)
    tiles[2].metric("Failed rules (latest run)", view.failed_rules, border=True)
    tiles[3].metric("Highest priority", _priority(view.highest_incident_priority), border=True)

    trends_tab, runs_tab, incidents_tab = st.tabs(["Metric trends", "Runs", "Incidents"])

    with trends_tab:
        rule_names = ctx.service.rule_names_for_dataset(dataset_id)
        if not rule_names:
            st.caption("No metric history recorded yet.")
        else:
            rule = st.selectbox("Rule", rule_names)
            points = ctx.service.metric_trend(dataset_id, rule, ctx.window, ctx.as_of)
            if not points:
                st.caption("No values for this rule in the time window.")
            else:
                st.altair_chart(_trend_chart(points), width="stretch")
                st.caption(
                    "Line: the measured value. Shaded: the range the threshold allowed on "
                    "each run. Red points: runs where this rule did not pass."
                )
                with st.expander("Latest threshold details"):
                    st.json(points[-1].threshold_details or "{}")

    with runs_tab:
        runs = ctx.service.quality_history(dataset_id, ctx.window, ctx.as_of)
        if not runs:
            st.caption("No validation runs in this window.")
        else:
            st.dataframe(
                [
                    {
                        "Started": r.started_at,
                        "Result": _STATUS_LABEL.get(r.overall_status, r.overall_status.upper()),
                        "Rules failed": f"{r.rules_failed} of {r.rules_evaluated}",
                        "Highest priority": _priority(r.highest_incident_priority),
                        "Run ID": str(r.run_id),
                    }
                    for r in runs
                ],
                hide_index=True,
                column_config={
                    "Started": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
                },
            )
            st.caption("Times in UTC. Inspect a run: `uv run python demo/inspect_run.py <run-id>`.")

    with incidents_tab:
        incidents = ctx.service.incident_history(ctx.window, ctx.as_of, dataset_id=dataset_id)
        if not incidents:
            st.caption("No incidents in this window.")
        else:
            _incident_table(incidents, show_dataset=False)


# -- app shell ----------------------------------------------------------------------


def _open_dataset(dataset_id: str, page: st.Page) -> None:
    """Switch to the Dataset page focused on ``dataset_id``."""
    st.session_state[_FOCUS] = dataset_id
    # A new table key on return means the Overview doesn't reopen the same row.
    st.session_state[_TABLE_GENERATION] = st.session_state.get(_TABLE_GENERATION, 0) + 1
    st.switch_page(page)


def main() -> None:
    st.set_page_config(
        page_title="Sentinel", page_icon="🛡️", layout="wide", initial_sidebar_state="collapsed"
    )
    as_of = datetime.now(UTC)

    # Rendered by the entrypoint, so it sits on every page and keeps its value
    # when you switch pages.
    status, picker = st.columns([3, 2], vertical_alignment="center")
    window_label = (
        picker.segmented_control(
            "Time window",
            list(_WINDOWS),
            default=_DEFAULT_WINDOW,
            key="window",
            label_visibility="collapsed",
            width="stretch",
        )
        or _DEFAULT_WINDOW  # a click on the selected option clears it
    )
    status.caption(f"🛡️ **Sentinel** · as of {as_of:%Y-%m-%d %H:%M} UTC · read-only")

    with _pool().connection() as conn:
        ctx = _Context(ObservabilityQueryService(conn), _WINDOWS[window_label], window_label, as_of)

        def dataset() -> None:
            _dataset_page(ctx)

        dataset_page = st.Page(dataset, title="Dataset", icon=":material/table_chart:")

        def overview() -> None:
            _overview_page(ctx, lambda d: _open_dataset(d, dataset_page))

        def incidents() -> None:
            _incidents_page(ctx)

        st.navigation(
            [
                st.Page(overview, title="Overview", icon=":material/dashboard:", default=True),
                st.Page(incidents, title="Incidents", icon=":material/notifications:"),
                dataset_page,
            ],
            position="top",
        ).run()


main()
