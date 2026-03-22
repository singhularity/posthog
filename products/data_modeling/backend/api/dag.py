from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.data_modeling.backend.models import DAG


class DAGSerializer(serializers.ModelSerializer):
    node_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = DAG
        fields = [
            "id",
            "name",
            "description",
            "node_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "node_count",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "name": {"help_text": "Human-readable name for this DAG"},
            "description": {"help_text": "Optional description of the DAG's purpose"},
        }

    def get_node_count(self, dag: DAG) -> int:
        return dag.node_set.count()

    def create(self, validated_data: dict) -> DAG:
        validated_data["team_id"] = self.context["team_id"]
        return super().create(validated_data)

    def validate_name(self, name: str) -> str:
        if name.startswith("conflict"):
            raise serializers.ValidationError("DAG names cannot start with 'conflict'.")
        return name


class DAGViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = DAG.objects.all()
    serializer_class = DAGSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id).exclude(name__startswith="conflict_").order_by("name")
