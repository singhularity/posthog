import pytest

from posthog.hogql import ast
from posthog.hogql.database.models import ExpressionField
from posthog.hogql.database.schema.traffic_type import (
    _user_agent_expr,
    create_bot_name_field,
    create_is_bot_field,
    create_traffic_category_field,
    create_traffic_type_field,
)
from posthog.hogql.functions.traffic_type import BOT_DEFINITIONS

FACTORY_FUNCTIONS = [
    create_is_bot_field,
    create_traffic_type_field,
    create_traffic_category_field,
    create_bot_name_field,
]
FIELD_NAMES = ["$virt_is_bot", "$virt_traffic_type", "$virt_traffic_category", "$virt_bot_name"]


class TestUserAgentExpr:
    def test_default_properties_path(self):
        expr = _user_agent_expr()
        assert isinstance(expr, ast.Call)
        assert expr.name == "coalesce"
        assert len(expr.args) == 2
        assert expr.args[0] == ast.Field(chain=["properties", "$raw_user_agent"])
        assert expr.args[1] == ast.Field(chain=["properties", "$user_agent"])

    def test_custom_properties_path(self):
        expr = _user_agent_expr(properties_path=["poe", "properties"])
        assert isinstance(expr, ast.Call)
        assert expr.name == "coalesce"
        assert expr.args[0] == ast.Field(chain=["poe", "properties", "$raw_user_agent"])
        assert expr.args[1] == ast.Field(chain=["poe", "properties", "$user_agent"])


class TestExpressionFieldFactories:
    @pytest.mark.parametrize(
        "factory_fn,field_name",
        list(zip(FACTORY_FUNCTIONS, FIELD_NAMES)),
    )
    def test_returns_expression_field_with_correct_name(self, factory_fn, field_name):
        field = factory_fn(name=field_name)
        assert isinstance(field, ExpressionField)
        assert field.name == field_name

    @pytest.mark.parametrize("factory_fn", FACTORY_FUNCTIONS)
    def test_isolate_scope_is_true(self, factory_fn):
        field = factory_fn(name="test")
        assert field.isolate_scope is True

    @pytest.mark.parametrize("factory_fn", FACTORY_FUNCTIONS)
    def test_expr_is_not_none(self, factory_fn):
        field = factory_fn(name="test")
        assert field.expr is not None

    @pytest.mark.parametrize("factory_fn", FACTORY_FUNCTIONS)
    def test_custom_properties_path_propagates(self, factory_fn):
        default_field = factory_fn(name="test")
        custom_field = factory_fn(name="test", properties_path=["poe", "properties"])
        assert default_field.expr != custom_field.expr


class TestIsBotField:
    def test_returns_or_expression(self):
        field = create_is_bot_field(name="$virt_is_bot")
        assert isinstance(field.expr, ast.Or)

    def test_has_correct_number_of_match_conditions(self):
        field = create_is_bot_field(name="$virt_is_bot")
        assert isinstance(field.expr, ast.Or)
        # One match per BOT_DEFINITION + one for empty UA
        assert len(field.expr.exprs) == len(BOT_DEFINITIONS) + 1

    def test_all_conditions_use_match(self):
        field = create_is_bot_field(name="$virt_is_bot")
        assert isinstance(field.expr, ast.Or)
        for expr in field.expr.exprs:
            assert isinstance(expr, ast.Call)
            assert expr.name == "match"

    def test_wraps_user_agent_in_ifnull(self):
        field = create_is_bot_field(name="$virt_is_bot")
        assert isinstance(field.expr, ast.Or)
        first_match = field.expr.exprs[0]
        safe_ua = first_match.args[0]
        assert isinstance(safe_ua, ast.Call)
        assert safe_ua.name == "ifNull"
        # ifNull wraps a coalesce($raw_user_agent, $user_agent)
        coalesce_call = safe_ua.args[0]
        assert isinstance(coalesce_call, ast.Call)
        assert coalesce_call.name == "coalesce"


class TestTrafficTypeField:
    def test_returns_if_expression(self):
        field = create_traffic_type_field(name="$virt_traffic_type")
        assert isinstance(field.expr, ast.Call)
        assert field.expr.name == "if"

    def test_default_value_is_regular(self):
        field = create_traffic_type_field(name="$virt_traffic_type")
        default = field.expr.args[1]
        assert isinstance(default, ast.Constant)
        assert default.value == "Regular"

    def test_labels_contain_expected_values(self):
        field = create_traffic_type_field(name="$virt_traffic_type")
        array_access = field.expr.args[2]
        assert isinstance(array_access, ast.ArrayAccess)
        labels = [e.value for e in array_access.array.exprs if isinstance(e, ast.Constant)]
        assert "AI Agent" in labels
        assert "Bot" in labels
        assert "Automation" in labels

    def test_uses_multiMatchAnyIndex(self):
        field = create_traffic_type_field(name="$virt_traffic_type")
        comparison = field.expr.args[0]
        assert isinstance(comparison, ast.CompareOperation)
        assert isinstance(comparison.left, ast.Call)
        assert comparison.left.name == "multiMatchAnyIndex"


class TestTrafficCategoryField:
    def test_returns_if_expression(self):
        field = create_traffic_category_field(name="$virt_traffic_category")
        assert isinstance(field.expr, ast.Call)
        assert field.expr.name == "if"

    def test_default_value_is_regular(self):
        field = create_traffic_category_field(name="$virt_traffic_category")
        default = field.expr.args[1]
        assert isinstance(default, ast.Constant)
        assert default.value == "regular"

    def test_labels_contain_expected_categories(self):
        field = create_traffic_category_field(name="$virt_traffic_category")
        array_access = field.expr.args[2]
        labels = [e.value for e in array_access.array.exprs if isinstance(e, ast.Constant)]
        assert "llm_crawler" in labels
        assert "search_crawler" in labels
        assert "seo_crawler" in labels
        assert "social_crawler" in labels
        assert "monitoring" in labels
        assert "http_client" in labels
        assert "headless_browser" in labels
        assert "no_user_agent" in labels


class TestBotNameField:
    def test_returns_if_expression(self):
        field = create_bot_name_field(name="$virt_bot_name")
        assert isinstance(field.expr, ast.Call)
        assert field.expr.name == "if"

    def test_default_value_is_empty_string(self):
        field = create_bot_name_field(name="$virt_bot_name")
        default = field.expr.args[1]
        assert isinstance(default, ast.Constant)
        assert default.value == ""

    def test_labels_contain_expected_bot_names(self):
        field = create_bot_name_field(name="$virt_bot_name")
        array_access = field.expr.args[2]
        labels = [e.value for e in array_access.array.exprs if isinstance(e, ast.Constant)]
        assert "Googlebot" in labels
        assert "ChatGPT" in labels
        assert "Claude" in labels
        assert "GPTBot" in labels
        assert "OpenAI Search" in labels
        assert "curl" in labels
        assert "" in labels
