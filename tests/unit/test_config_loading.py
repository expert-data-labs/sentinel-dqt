from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from sentinel.config_loading import load_yaml_model


class _Widget(BaseModel):
    name: str
    count: int


class _WidgetLoadError(Exception):
    pass


def test_loads_a_valid_model(tmp_path: Path) -> None:
    path = tmp_path / "widget.yaml"
    path.write_text("name: gizmo\ncount: 3\n")

    widget = load_yaml_model(path, _Widget, _WidgetLoadError)

    assert widget.name == "gizmo"
    assert widget.count == 3


def test_missing_file_raises_the_given_error_class(tmp_path: Path) -> None:
    with pytest.raises(_WidgetLoadError, match="could not be read"):
        load_yaml_model(tmp_path / "does_not_exist.yaml", _Widget, _WidgetLoadError)


def test_invalid_yaml_syntax_raises_the_given_error_class(tmp_path: Path) -> None:
    path = tmp_path / "widget.yaml"
    path.write_text("name: gizmo\n  count: 3\n")

    with pytest.raises(_WidgetLoadError, match="not valid YAML"):
        load_yaml_model(path, _Widget, _WidgetLoadError)


def test_empty_file_raises_the_given_error_class(tmp_path: Path) -> None:
    path = tmp_path / "widget.yaml"
    path.write_text("")

    with pytest.raises(_WidgetLoadError, match="file is empty"):
        load_yaml_model(path, _Widget, _WidgetLoadError)


def test_non_mapping_top_level_raises_the_given_error_class(tmp_path: Path) -> None:
    path = tmp_path / "widget.yaml"
    path.write_text("- just\n- a\n- list\n")

    with pytest.raises(_WidgetLoadError, match="expected a mapping"):
        load_yaml_model(path, _Widget, _WidgetLoadError)


def test_schema_violation_raises_the_given_error_class(tmp_path: Path) -> None:
    path = tmp_path / "widget.yaml"
    path.write_text("name: gizmo\n")  # missing required 'count'

    with pytest.raises(_WidgetLoadError, match="failed validation"):
        load_yaml_model(path, _Widget, _WidgetLoadError)
