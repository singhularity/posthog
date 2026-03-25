import pytest

from posthog.hogql import ast
from posthog.hogql.database.models import ExpressionField
from posthog.hogql.database.schema.traffic_type import (
    create_bot_name_field,
    create_is_bot_field,
    create_traffic_category_field,
    create_traffic_type_field,
)


class TestTrafficTypeExpressionFields:
    @pytest.mark.parametrize(
        "factory_fn,field_name",
        [
            (create_is_bot_field, "$virt_is_bot"),
            (create_traffic_type_field, "$virt_traffic_type"),
            (create_traffic_category_field, "$virt_traffic_category"),
            (create_bot_name_field, "$virt_bot_name"),
        ],
    )
    def test_factory_returns_expression_field(self, factory_fn, field_name):
        field = factory_fn(name=field_name)
        assert isinstance(field, ExpressionField)
        assert field.name == field_name

    @pytest.mark.parametrize(
        "factory_fn",
        [create_is_bot_field, create_traffic_type_field, create_traffic_category_field, create_bot_name_field],
    )
    def test_isolate_scope_is_true(self, factory_fn):
        field = factory_fn(name="test")
        assert field.isolate_scope is True

    @pytest.mark.parametrize(
        "factory_fn",
        [create_traffic_type_field, create_traffic_category_field, create_bot_name_field],
    )
    def test_string_fields_use_if_with_array_lookup(self, factory_fn):
        field = factory_fn(name="test")
        assert isinstance(field.expr, ast.Call)
        assert field.expr.name == "if"

    def test_is_bot_returns_or_expression(self):
        field = create_is_bot_field(name="test")
        assert isinstance(field.expr, ast.Or)

    @pytest.mark.parametrize(
        "factory_fn",
        [create_is_bot_field, create_traffic_type_field, create_traffic_category_field, create_bot_name_field],
    )
    def test_custom_properties_path(self, factory_fn):
        field = factory_fn(name="test", properties_path=["poe", "properties"])
        assert isinstance(field, ExpressionField)
        assert field.isolate_scope is True
