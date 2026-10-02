"""Sentinel observability dashboard (Streamlit).

Run with:

    uv sync --group dashboard
    uv run streamlit run dashboard/app.py

Display only: all data comes from ObservabilityQueryService. Reads the Postgres
store at SENTINEL_DATABASE_URL, so run ``sentinel validate <dataset>`` a few
times first. Each page render borrows a connection from a shared pool, so many
viewers can use it at once.
"""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st
from psycopg_pool import ConnectionPool

from sentinel.observability.queries import ObservabilityQueryService, TimeWindow
from sentinel.persistence.engine import StoreConnection, create_pool

_HEALTH_GLYPH: dict[str, str] = {
    "healthy": "🟢 healthy",
    "degraded": "🟡 degraded",
    "critical": "🔴 critical",
    "unknown": "⚪ unknown",
}

_WINDOW_LABELS: dict[str, TimeWindow] = {
    "Last 24 hours": TimeWindow.LAST_24H,
    "Last 7 days": TimeWindow.LAST_7D,
    "Last 30 days": TimeWindow.LAST_30D,
}

_ALL_DATASETS = "(all datasets)"


@st.cache_resource
def _pool() -> ConnectionPool[StoreConnection]:
    """One connection pool per Streamlit server, shared by all sessions."""
    return create_pool(min_size=1, max_size=5)


def _dataset_health_table(views: list) -> list[dict[str, object]]:
    return [
        {
            "Dataset": v.dataset_name,
            "Health": _HEALTH_GLYPH[v.health.value],
            "Latest validation": v.latest_validation_at,
            "Highest priority": v.highest_incident_priority or "-",
            "Failed rules": v.failed_rules,
        }
        for v in views
    ]


def main() -> None:
    st.set_page_config(page_title="Sentinel — Data Reliability", layout="wide")
    with _pool().connection() as conn:
        _render(ObservabilityQueryService(conn))


def _render(service: ObservabilityQueryService) -> None:
    as_of = datetime.now(UTC)

    st.title("Sentinel — Data Reliability")
    st.caption(f"As of {as_of.isoformat(timespec='seconds')} · read-only")

    health_views = service.all_datasets_health()
    dataset_names = sorted(v.dataset_name for v in health_views)

    window_label = st.sidebar.selectbox(
        "Time window",
        list(_WINDOW_LABELS),
        index=1,  # default: last 7 days
    )
    window = _WINDOW_LABELS[window_label]
    st.sidebar.caption(
        "Applies to every view below except Dataset Health, which always "
        "reflects each dataset's latest run."
    )

    selected_dataset = st.sidebar.selectbox("Dataset (drill-down)", [_ALL_DATASETS, *dataset_names])
    dataset_id = None if selected_dataset == _ALL_DATASETS else selected_dataset

    st.header("Dataset Health")
    st.dataframe(_dataset_health_table(health_views), use_container_width=True, hide_index=True)

    st.header("Recent Incidents")
    incidents = service.incident_history(window, as_of, dataset_id=dataset_id)
    if incidents:
        st.dataframe(
            [
                {
                    "When": i.occurred_at,
                    "Dataset": i.dataset_id,
                    "Rule": i.rule_name,
                    "Priority": i.priority.upper(),
                    "Score": round(i.score, 1),
                    "Reason": i.top_reason or "",
                }
                for i in incidents
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No incidents in this window.")

    st.header("Failed Rules")
    failed = service.failed_rules(window, as_of, dataset_id=dataset_id)
    if failed:
        st.dataframe(
            [
                {
                    "Dataset": f.dataset_id,
                    "Rule": f.rule_name,
                    "Failures": f.failure_count,
                    "Latest failure": f.latest_failure_at,
                    "Current priority": (f.current_priority or "-").upper(),
                }
                for f in sorted(failed, key=lambda f: f.failure_count, reverse=True)
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No failed rules in this window.")

    st.header("Recurring Failures")
    st.caption(
        "Recurring = the same dataset + rule failed more than once within the selected window. "
        "Persistent = still failing as of the most recent evaluation."
    )
    recurring = service.recurring_failures(window, as_of, dataset_id=dataset_id)
    if recurring:
        st.dataframe(
            [
                {
                    "Dataset": r.dataset_id,
                    "Rule": r.rule_name,
                    "Failures": r.failure_count,
                    "Last seen": r.last_seen_at,
                    "Status": r.classification.value.replace("_", " ").title(),
                }
                for r in sorted(recurring, key=lambda r: r.failure_count, reverse=True)
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No recurring failures in this window.")

    st.header("Metric Trends")
    if dataset_id is None:
        st.caption("Select a dataset in the sidebar to see its metric trends.")
    else:
        rule_names = service.rule_names_for_dataset(dataset_id)
        if not rule_names:
            st.caption(f"No metric history recorded yet for {dataset_id!r}.")
        else:
            metric_name = st.selectbox("Metric", rule_names)
            points = service.metric_trend(dataset_id, metric_name, window, as_of)
            if points:
                st.line_chart(
                    {
                        "computed_at": [p.computed_at for p in points],
                        "value": [p.value for p in points],
                    },
                    x="computed_at",
                    y="value",
                )
                with st.expander("Latest threshold details"):
                    latest = points[-1]
                    st.json(latest.threshold_details or "{}")
            else:
                st.caption("No points for this metric in the selected window.")

    if dataset_id is not None:
        st.header(f"Quality History — {dataset_id}")
        history = service.quality_history(dataset_id, window, as_of)
        if history:
            st.dataframe(
                [
                    {
                        "Run started": h.started_at,
                        "Rules evaluated": h.rules_evaluated,
                        "Rules failed": h.rules_failed,
                        "Overall result": h.overall_status.upper(),
                        "Highest priority": (h.highest_incident_priority or "-").upper(),
                    }
                    for h in history
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No validation runs in this window.")


main()
