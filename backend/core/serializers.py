from rest_framework import serializers

from core.models import AgentEvent, AgentRun


class AgentEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentEvent
        fields = [
            "id",
            "step_index",
            "state",
            "input_json",
            "output_json",
            "tool_name",
            "tool_input",
            "tool_output",
            "policy_result",
            "created_at",
        ]


class AgentRunSerializer(serializers.ModelSerializer):
    events = AgentEventSerializer(many=True, read_only=True, source="agentevent_set")

    class Meta:
        model = AgentRun
        fields = [
            "id",
            "created_at",
            "model_provider",
            "events",
        ]


class AgentRunListSerializer(serializers.ModelSerializer):
    run_id = serializers.UUIDField(source="id", read_only=True)
    event_count = serializers.SerializerMethodField()
    last_state = serializers.SerializerMethodField()
    last_tool = serializers.SerializerMethodField()

    class Meta:
        model = AgentRun
        fields = [
            "run_id",
            "created_at",
            "model_provider",
            "event_count",
            "last_state",
            "last_tool",
        ]

    def _get_last_event(self, obj):
        last_event = getattr(obj, "_last_event", None)
        if last_event is None:
            last_event = obj.agentevent_set.order_by("-step_index", "-id").first()
            setattr(obj, "_last_event", last_event)
        return last_event

    def get_event_count(self, obj):
        return obj.agentevent_set.count()

    def get_last_state(self, obj):
        last_event = self._get_last_event(obj)
        return getattr(last_event, "state", None)

    def get_last_tool(self, obj):
        last_event = self._get_last_event(obj)
        return getattr(last_event, "tool_name", None)
