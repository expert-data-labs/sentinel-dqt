"""BigQueryDataSource: reads one BigQuery table or view.

``config_reference``: ``bigquery://project/dataset?table=orders`` (optionally
``&location=EU``). Credentials come from Google Application Default
Credentials (``gcloud auth application-default login`` locally, or
GOOGLE_APPLICATION_CREDENTIALS / the workload identity in production), so
none appear in the config. Requires the ``bigquery`` extra.

Each check is a query, and BigQuery bills by bytes scanned: ``row_count``
reads table metadata only, the others scan one column each.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import unquote, urlsplit

from sentinel.datasources._common import (
    ConfigReferenceError,
    import_driver,
    pop_url_param,
    url_params,
)
from sentinel.datasources.registry import register_data_source
from sentinel.datasources.sql_base import SqlDataSource

_EXAMPLE = "bigquery://my-project/my_dataset?table=orders"
_TYPES = {
    "STRING": "string",
    "INT64": "integer",
    "INTEGER": "integer",
    "FLOAT64": "float",
    "FLOAT": "float",
    "NUMERIC": "decimal",
    "BIGNUMERIC": "decimal",
    "BOOL": "boolean",
    "BOOLEAN": "boolean",
    "TIMESTAMP": "timestamp",
    "DATETIME": "timestamp",
    "DATE": "date",
}


def _canonical_type(field_type: str, mode: str = "NULLABLE") -> str:
    """Map a BigQuery schema field type to a canonical type. Repeated fields are unknown."""
    if mode.upper() == "REPEATED":
        return "unknown"
    return _TYPES.get(field_type.upper(), "unknown")


def _parse_config_reference(config_reference: str) -> tuple[str, str, str, str | None]:
    """(project, dataset, table, location) from ``config_reference``."""
    url, table = pop_url_param(config_reference, "table", example=_EXAMPLE)
    parts = urlsplit(url)
    dataset = unquote(parts.path.strip("/"))
    if parts.scheme != "bigquery" or not parts.hostname or not dataset or "/" in dataset:
        raise ConfigReferenceError(f"Expected a BigQuery URL like {_EXAMPLE!r}")
    return parts.hostname, dataset, table, url_params(url).get("location")


@register_data_source
class BigQueryDataSource(SqlDataSource):
    """Reads one BigQuery table or view."""

    source_type: ClassVar[str] = "bigquery"
    _quote_char = "`"

    def __init__(self, config_reference: str | None) -> None:
        if config_reference is None:
            raise ValueError(f"BigQueryDataSource requires a config_reference, e.g. {_EXAMPLE!r}")
        self._project, self._dataset, self._name, location = _parse_config_reference(
            config_reference
        )
        bigquery = import_driver("google.cloud.bigquery", "bigquery")
        self._client = bigquery.Client(project=self._project, location=location)

    def _table(self) -> str:
        return ".".join(self._quote(p) for p in (self._project, self._dataset, self._name))

    def _scalar(self, query: str) -> Any:
        rows = list(self._client.query(query).result())
        assert len(rows) == 1  # aggregates always return one row
        return rows[0][0]

    def columns(self) -> dict[str, str]:
        table = self._client.get_table(f"{self._project}.{self._dataset}.{self._name}")
        return {field.name: _canonical_type(field.field_type, field.mode) for field in table.schema}
