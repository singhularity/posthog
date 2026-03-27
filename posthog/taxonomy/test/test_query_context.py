import re

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.taxonomy.property_definition_api import QueryContext


def normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def base_query_context() -> QueryContext:
    return QueryContext(
        project_id=1,
        table="posthog_propertydefinition",
        property_definition_fields="posthog_propertydefinition.*",
        property_definition_table="posthog_propertydefinition",
        limit=100,
        offset=0,
        should_join_event_property=False,
    )


class TestQueryContextVerifiedFilter(BaseTest):
    def test_with_verified_true_and_ee_enabled_adds_verified_true_condition(self):
        ctx = base_query_context().with_verified_filter(True, True)
        sql = normalize_sql(ctx.as_sql(order_by_verified=False))

        assert "AND verified = true" in sql

    def test_with_verified_false_and_ee_enabled_adds_verified_null_or_false_condition(self):
        ctx = base_query_context().with_verified_filter(False, True)
        sql = normalize_sql(ctx.as_sql(order_by_verified=False))

        assert "AND (verified IS NULL OR verified = false)" in sql

    def test_with_verified_true_and_ee_disabled_leaves_sql_unchanged(self):
        base_ctx = base_query_context()
        ctx = base_ctx.with_verified_filter(True, False)
        sql = normalize_sql(ctx.as_sql(order_by_verified=False))

        assert "verified" not in sql

    def test_with_verified_none_leaves_sql_unchanged(self):
        base_ctx = base_query_context()
        ctx = base_ctx.with_verified_filter(None, True)
        sql = normalize_sql(ctx.as_sql(order_by_verified=False))

        assert "verified = true" not in sql
        assert "verified IS NULL" not in sql

    def test_verified_filter_appears_in_count_sql(self):
        ctx = base_query_context().with_verified_filter(True, True)
        count_sql = normalize_sql(ctx.as_count_sql())

        assert "AND verified = true" in count_sql

    def test_verified_false_filter_appears_in_count_sql(self):
        ctx = base_query_context().with_verified_filter(False, True)
        count_sql = normalize_sql(ctx.as_count_sql())

        assert "AND (verified IS NULL OR verified = false)" in count_sql


class TestQueryContextPropertyNameTypeFilter(BaseTest):
    @parameterized.expand(
        [
            ("posthog", "AND posthog_propertydefinition.name LIKE '$%'"),
            ("custom", "AND posthog_propertydefinition.name NOT LIKE '$%'"),
        ]
    )
    def test_property_name_type_filter_adds_correct_condition(self, property_name_type: str, expected_fragment: str):
        ctx = base_query_context().with_property_name_type_filter(property_name_type)
        sql = normalize_sql(ctx.as_sql(order_by_verified=False))

        assert expected_fragment in sql

    def test_with_property_name_type_all_leaves_sql_unchanged(self):
        base_ctx = base_query_context()
        ctx = base_ctx.with_property_name_type_filter("all")

        assert ctx.extra_where_conditions == base_ctx.extra_where_conditions

    def test_property_name_type_posthog_appears_in_count_sql(self):
        ctx = base_query_context().with_property_name_type_filter("posthog")
        count_sql = normalize_sql(ctx.as_count_sql())

        assert "AND posthog_propertydefinition.name LIKE '$%'" in count_sql

    def test_property_name_type_custom_appears_in_count_sql(self):
        ctx = base_query_context().with_property_name_type_filter("custom")
        count_sql = normalize_sql(ctx.as_count_sql())

        assert "AND posthog_propertydefinition.name NOT LIKE '$%'" in count_sql


class TestQueryContextTagsFilter(BaseTest):
    def test_with_tags_filter_adds_inner_join_on_taggeditem(self):
        ctx = base_query_context().with_tags_filter(["tag1", "tag2"])
        sql = normalize_sql(ctx.as_sql(order_by_verified=False))

        assert "INNER JOIN posthog_taggeditem" in sql

    def test_with_tags_filter_adds_inner_join_on_tag(self):
        ctx = base_query_context().with_tags_filter(["tag1", "tag2"])
        sql = normalize_sql(ctx.as_sql(order_by_verified=False))

        assert "INNER JOIN posthog_tag" in sql

    def test_with_tags_filter_adds_tag_name_where_condition(self):
        ctx = base_query_context().with_tags_filter(["tag1", "tag2"])
        sql = normalize_sql(ctx.as_sql(order_by_verified=False))

        assert "posthog_tag.name = ANY(%(tags_list)s)" in sql

    def test_with_tags_filter_stores_tags_in_params(self):
        ctx = base_query_context().with_tags_filter(["tag1", "tag2"])

        assert ctx.params["tags_list"] == ["tag1", "tag2"]

    def test_with_empty_tags_filter_leaves_sql_unchanged(self):
        base_ctx = base_query_context()
        ctx = base_ctx.with_tags_filter([])

        assert ctx.tags_join == base_ctx.tags_join
        assert ctx.extra_where_conditions == base_ctx.extra_where_conditions

    def test_tags_filter_adds_inner_join_in_count_sql(self):
        ctx = base_query_context().with_tags_filter(["tag1"])
        count_sql = normalize_sql(ctx.as_count_sql())

        assert "INNER JOIN posthog_taggeditem" in count_sql
        assert "INNER JOIN posthog_tag" in count_sql
        assert "posthog_tag.name = ANY(%(tags_list)s)" in count_sql

    def test_tags_join_causes_distinct_in_select(self):
        ctx = base_query_context().with_tags_filter(["tag1"])
        sql = normalize_sql(ctx.as_sql(order_by_verified=False))

        assert sql.startswith("SELECT DISTINCT")

    def test_no_tags_join_means_no_distinct_in_select(self):
        ctx = base_query_context()
        sql = normalize_sql(ctx.as_sql(order_by_verified=False))

        assert "SELECT DISTINCT" not in sql
