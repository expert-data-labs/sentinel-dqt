"""MongoDataSource helpers (real MongoDB: tests/integration/test_adapter_contract.py)."""

from __future__ import annotations

import pytest

from sentinel.datasources._common import ConfigReferenceError
from sentinel.datasources.mongodb_source import _canonical_type, _parse_config_reference


def test_parse_config_reference_keeps_other_options_for_the_client() -> None:
    url, database, collection, sample = _parse_config_reference(
        "mongodb://u:p@h:27017/shop?collection=orders&authSource=admin&schema_sample=50"
    )
    assert (database, collection, sample) == ("shop", "orders", 50)
    assert url == "mongodb://u:p@h:27017/shop?authSource=admin"


def test_srv_urls_are_accepted() -> None:
    _, database, _, sample = _parse_config_reference(
        "mongodb+srv://u:p@cluster0.example.net/shop?collection=orders"
    )
    assert (database, sample) == ("shop", 1000)


@pytest.mark.parametrize(
    "bad", ["mongodb://h:27017?collection=orders", "mongodb://h/shop", "pg://h/shop?collection=o"]
)
def test_bad_urls_are_rejected(bad: str) -> None:
    with pytest.raises(ConfigReferenceError):
        _parse_config_reference(bad)


@pytest.mark.parametrize(
    ("types", "expected"),
    [
        ({"string"}, "string"),
        ({"int", "null"}, "integer"),
        ({"long"}, "integer"),
        ({"double", "missing"}, "float"),
        ({"date"}, "timestamp"),
        ({"objectId"}, "string"),
        ({"int", "string"}, "unknown"),  # mixed types
        ({"object"}, "unknown"),
        ({"null"}, "unknown"),
    ],
)
def test_canonical_type(types: set[str], expected: str) -> None:
    assert _canonical_type(types) == expected
