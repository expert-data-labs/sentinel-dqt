"""MongoDataSource: reads one MongoDB collection.

``config_reference``::

    mongodb://user:${MONGO_PASSWORD}@host:27017/database?collection=orders&authSource=admin

``mongodb+srv://`` URLs work too. Optional ``schema_sample=N`` (default 1000)
sets how many documents ``columns()`` samples. Requires the ``mongodb`` extra.

How the capabilities map onto documents:

- Column names are field paths; dotted paths (``customer.id``) reach into
  sub-documents.
- A missing field counts as null, so ``null_count`` covers both.
- ``distinct_count`` and ``max_value`` ignore nulls and missing fields, like SQL.
  Comparisons across different BSON types follow MongoDB's type ordering.
- ``columns()`` infers the schema from a random sample of documents, top-level
  fields only. A field seen with more than one type is ``unknown``; ObjectId is
  reported as ``string``. An empty collection has no columns.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import urlsplit

from sentinel.datasources._common import (
    ConfigReferenceError,
    as_utc,
    import_driver,
    pop_url_param,
    url_params,
)
from sentinel.datasources.registry import register_data_source

_EXAMPLE = "mongodb://user:password@host:27017/database?collection=orders"
_DEFAULT_SCHEMA_SAMPLE = 1000
_TYPES = {
    "string": "string",
    "objectId": "string",
    "int": "integer",
    "long": "integer",
    "double": "float",
    "decimal": "decimal",
    "bool": "boolean",
    "date": "timestamp",
}
_IGNORED_TYPES = {"null", "missing", "undefined"}


def _canonical_type(bson_types: set[str]) -> str:
    """Map the BSON types seen for one field to a canonical type (``unknown`` if mixed)."""
    types = bson_types - _IGNORED_TYPES
    if len(types) != 1:
        return "unknown"
    return _TYPES.get(types.pop(), "unknown")


def _parse_config_reference(config_reference: str) -> tuple[str, str, str, int]:
    """(client URL, database, collection, schema sample size)."""
    url, collection = pop_url_param(config_reference, "collection", example=_EXAMPLE)
    sample = int(url_params(url).get("schema_sample", _DEFAULT_SCHEMA_SAMPLE))
    if "schema_sample" in url_params(url):
        url, _ = pop_url_param(url, "schema_sample", example=_EXAMPLE)
    parts = urlsplit(url)
    database = parts.path.strip("/")
    if parts.scheme not in {"mongodb", "mongodb+srv"} or not database:
        raise ConfigReferenceError(f"Expected a MongoDB URL with a database, e.g. {_EXAMPLE!r}")
    return url, database, collection, sample


def _not_null(field: str) -> dict[str, Any]:
    return {"$match": {field: {"$ne": None}}}


@register_data_source
class MongoDataSource:
    """Reads one MongoDB collection."""

    source_type: ClassVar[str] = "mongodb"

    def __init__(self, config_reference: str | None) -> None:
        if config_reference is None:
            raise ValueError(f"MongoDataSource requires a config_reference, e.g. {_EXAMPLE!r}")
        url, database, collection, self._schema_sample = _parse_config_reference(config_reference)
        pymongo = import_driver("pymongo", "mongodb")
        self._client = pymongo.MongoClient(url, tz_aware=True, serverSelectionTimeoutMS=10_000)
        self._collection = self._client[database][collection]

    def _aggregate(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return list(self._collection.aggregate(pipeline, allowDiskUse=True))

    def row_count(self) -> int:
        return int(self._collection.count_documents({}))

    def null_count(self, column: str) -> int:
        return int(self._collection.count_documents({column: None}))

    def distinct_count(self, column: str) -> int:
        result = self._aggregate(
            [_not_null(column), {"$group": {"_id": f"${column}"}}, {"$count": "n"}]
        )
        return int(result[0]["n"]) if result else 0

    def max_value(self, column: str) -> Any:
        result = self._aggregate(
            [
                _not_null(column),
                {"$sort": {column: -1}},
                {"$limit": 1},
                {"$project": {"_id": 0, "value": f"${column}"}},
            ]
        )
        return as_utc(result[0].get("value")) if result else None

    def columns(self) -> dict[str, str]:
        result = self._aggregate(
            [
                {"$sample": {"size": self._schema_sample}},
                {"$project": {"fields": {"$objectToArray": "$$ROOT"}}},
                {"$unwind": "$fields"},
                {"$group": {"_id": "$fields.k", "types": {"$addToSet": {"$type": "$fields.v"}}}},
                {"$sort": {"_id": 1}},
            ]
        )
        return {row["_id"]: _canonical_type(set(row["types"])) for row in result}
