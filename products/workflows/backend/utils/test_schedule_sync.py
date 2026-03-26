from unittest import TestCase

from products.workflows.backend.utils.schedule_sync import _resolve_variables


class TestResolveVariables(TestCase):
    def test_empty_defaults_and_empty_overrides(self):
        hog_flow = type("HogFlow", (), {"variables": []})()
        schedule = type("Schedule", (), {"variables": {}})()
        assert _resolve_variables(hog_flow, schedule) == {}

    def test_defaults_only(self):
        hog_flow = type("HogFlow", (), {"variables": [{"key": "a", "default": 1}, {"key": "b", "default": 2}]})()
        schedule = type("Schedule", (), {"variables": {}})()
        assert _resolve_variables(hog_flow, schedule) == {"a": 1, "b": 2}

    def test_overrides_replace_defaults(self):
        hog_flow = type("HogFlow", (), {"variables": [{"key": "a", "default": 1}, {"key": "b", "default": 2}]})()
        schedule = type("Schedule", (), {"variables": {"a": 99}})()
        result = _resolve_variables(hog_flow, schedule)
        assert result == {"a": 99, "b": 2}

    def test_overrides_add_new_keys(self):
        hog_flow = type("HogFlow", (), {"variables": [{"key": "a", "default": 1}]})()
        schedule = type("Schedule", (), {"variables": {"b": "new"}})()
        result = _resolve_variables(hog_flow, schedule)
        assert result == {"a": 1, "b": "new"}

    def test_none_variables_on_hogflow(self):
        hog_flow = type("HogFlow", (), {"variables": None})()
        schedule = type("Schedule", (), {"variables": {"a": 1}})()
        assert _resolve_variables(hog_flow, schedule) == {"a": 1}

    def test_variable_without_default(self):
        hog_flow = type("HogFlow", (), {"variables": [{"key": "a"}, {"key": "b", "default": 2}]})()
        schedule = type("Schedule", (), {"variables": {}})()
        assert _resolve_variables(hog_flow, schedule) == {"a": None, "b": 2}
