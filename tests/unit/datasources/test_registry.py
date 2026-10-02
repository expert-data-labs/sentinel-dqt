from __future__ import annotations

from collections.abc import Iterator
from typing import Any, ClassVar

import pytest

from sentinel.datasources import (
    DataSourceNotRegisteredError,
    get_data_source,
    register_data_source,
)
from sentinel.datasources import registry as registry_module
from sentinel.datasources._common import ConfigReferenceError


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    """Save, clear and restore the registry around each test."""
    original = dict(registry_module._REGISTRY)
    registry_module._REGISTRY.clear()
    yield
    registry_module._REGISTRY.clear()
    registry_module._REGISTRY.update(original)


def test_register_and_resolve_a_dummy_source() -> None:
    @register_data_source
    class EchoSource:
        source_type: ClassVar[str] = "echo"

        def __init__(self, config_reference: str | None) -> None:
            self.config_reference = config_reference

        def row_count(self) -> int:
            return 0

        def null_count(self, column: str) -> int:
            return 0

        def distinct_count(self, column: str) -> int:
            return 0

        def max_value(self, column: str) -> Any:
            return None

        def columns(self) -> dict[str, str]:
            return {}

    source = get_data_source("echo", "some/path.csv")
    assert isinstance(source, EchoSource)
    assert source.config_reference == "some/path.csv"


def test_unregistered_source_type_raises_with_known_types_listed() -> None:
    @register_data_source
    class EchoSource:
        source_type: ClassVar[str] = "echo"

        def __init__(self, config_reference: str | None) -> None:
            pass

        def row_count(self) -> int:
            return 0

        def null_count(self, column: str) -> int:
            return 0

        def distinct_count(self, column: str) -> int:
            return 0

        def max_value(self, column: str) -> Any:
            return None

        def columns(self) -> dict[str, str]:
            return {}

    with pytest.raises(DataSourceNotRegisteredError, match="echo"):
        get_data_source("does_not_exist", None)


def test_registering_a_duplicate_source_type_raises() -> None:
    @register_data_source
    class FirstSource:
        source_type: ClassVar[str] = "duplicate"

        def __init__(self, config_reference: str | None) -> None:
            pass

        def row_count(self) -> int:
            return 0

        def null_count(self, column: str) -> int:
            return 0

        def distinct_count(self, column: str) -> int:
            return 0

        def max_value(self, column: str) -> Any:
            return None

        def columns(self) -> dict[str, str]:
            return {}

    with pytest.raises(ValueError, match="duplicate"):

        @register_data_source
        class SecondSource:
            source_type: ClassVar[str] = "duplicate"

            def __init__(self, config_reference: str | None) -> None:
                pass

            def row_count(self) -> int:
                return 1

            def null_count(self, column: str) -> int:
                return 0

            def distinct_count(self, column: str) -> int:
                return 0

            def max_value(self, column: str) -> Any:
                return None

            def columns(self) -> dict[str, str]:
                return {}


def _recording_source() -> type[Any]:
    @register_data_source
    class RecordingSource:
        source_type: ClassVar[str] = "recording"

        def __init__(self, config_reference: str | None) -> None:
            self.config_reference = config_reference

        def row_count(self) -> int:
            return 0

        def null_count(self, column: str) -> int:
            return 0

        def distinct_count(self, column: str) -> int:
            return 0

        def max_value(self, column: str) -> Any:
            return None

        def columns(self) -> dict[str, str]:
            return {}

    return RecordingSource


def test_env_var_references_are_expanded_before_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _recording_source()
    monkeypatch.setenv("WAREHOUSE_PASSWORD", "s3cret")

    source = get_data_source("recording", "db://etl:${WAREHOUSE_PASSWORD}@host/db?table=t")

    assert source.config_reference == "db://etl:s3cret@host/db?table=t"  # type: ignore[attr-defined]


def test_an_unset_env_var_fails_with_its_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _recording_source()
    monkeypatch.delenv("WAREHOUSE_PASSWORD", raising=False)

    with pytest.raises(ConfigReferenceError, match="WAREHOUSE_PASSWORD"):
        get_data_source("recording", "db://etl:${WAREHOUSE_PASSWORD}@host/db?table=t")
