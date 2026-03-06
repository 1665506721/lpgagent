import uuid

from django.db import models


class UserProfile(models.Model):
    name = models.CharField(max_length=64)
    phone = models.CharField(max_length=32, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Order(models.Model):
    STATUS_CREATED = "CREATED"
    STATUS_CONFIRMED = "CONFIRMED"
    STATUS_DISPATCHED = "DISPATCHED"
    STATUS_DELIVERING = "DELIVERING"
    STATUS_DONE = "DONE"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES = [
        (STATUS_CREATED, STATUS_CREATED),
        (STATUS_CONFIRMED, STATUS_CONFIRMED),
        (STATUS_DISPATCHED, STATUS_DISPATCHED),
        (STATUS_DELIVERING, STATUS_DELIVERING),
        (STATUS_DONE, STATUS_DONE),
        (STATUS_CANCELLED, STATUS_CANCELLED),
    ]

    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    product_type = models.CharField(max_length=64)
    quantity = models.IntegerField()
    status = models.CharField(max_length=32, choices=STATUS_CHOICES)
    address = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Ticket(models.Model):
    CATEGORY_DELIVERY_DELAY = "DELIVERY_DELAY"
    CATEGORY_SERVICE_ISSUE = "SERVICE_ISSUE"
    CATEGORY_GAS_LEAK = "GAS_LEAK"
    CATEGORY_REFUND = "REFUND"
    CATEGORY_OTHER = "OTHER"

    CATEGORY_CHOICES = [
        (CATEGORY_DELIVERY_DELAY, CATEGORY_DELIVERY_DELAY),
        (CATEGORY_SERVICE_ISSUE, CATEGORY_SERVICE_ISSUE),
        (CATEGORY_GAS_LEAK, CATEGORY_GAS_LEAK),
        (CATEGORY_REFUND, CATEGORY_REFUND),
        (CATEGORY_OTHER, CATEGORY_OTHER),
    ]

    STATUS_OPEN = "OPEN"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_RESOLVED = "RESOLVED"
    STATUS_CLOSED = "CLOSED"

    STATUS_CHOICES = [
        (STATUS_OPEN, STATUS_OPEN),
        (STATUS_IN_PROGRESS, STATUS_IN_PROGRESS),
        (STATUS_RESOLVED, STATUS_RESOLVED),
        (STATUS_CLOSED, STATUS_CLOSED),
    ]

    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True)
    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES)
    description = models.TextField()
    status = models.CharField(max_length=32, choices=STATUS_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)


class MaintenanceRequest(models.Model):
    STATUS_OPEN = "OPEN"
    STATUS_ASSIGNED = "ASSIGNED"
    STATUS_DONE = "DONE"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES = [
        (STATUS_OPEN, STATUS_OPEN),
        (STATUS_ASSIGNED, STATUS_ASSIGNED),
        (STATUS_DONE, STATUS_DONE),
        (STATUS_CANCELLED, STATUS_CANCELLED),
    ]

    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    issue = models.TextField()
    status = models.CharField(max_length=32, choices=STATUS_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)


class AgentRun(models.Model):
    PROVIDER_OPENAI = "OPENAI"
    PROVIDER_ANTHROPIC = "ANTHROPIC"
    PROVIDER_LOCAL = "LOCAL"

    PROVIDER_CHOICES = [
        (PROVIDER_OPENAI, PROVIDER_OPENAI),
        (PROVIDER_ANTHROPIC, PROVIDER_ANTHROPIC),
        (PROVIDER_LOCAL, PROVIDER_LOCAL),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    model_provider = models.CharField(max_length=16, choices=PROVIDER_CHOICES)


class AgentEvent(models.Model):
    STATE_INIT = "INIT"
    STATE_PLANNING = "PLANNING"
    STATE_VALIDATE = "VALIDATE"
    STATE_EXEC_TOOL = "EXEC_TOOL"
    STATE_RESPOND = "RESPOND"
    STATE_DONE = "DONE"
    STATE_ERROR = "ERROR"
    STATE_TOOL_EXEC = "TOOL_EXEC"
    STATE_FALLBACK = "FALLBACK"

    STATE_CHOICES = [
        (STATE_INIT, STATE_INIT),
        (STATE_PLANNING, STATE_PLANNING),
        (STATE_VALIDATE, STATE_VALIDATE),
        (STATE_EXEC_TOOL, STATE_EXEC_TOOL),
        (STATE_RESPOND, STATE_RESPOND),
        (STATE_DONE, STATE_DONE),
        (STATE_ERROR, STATE_ERROR),
        (STATE_TOOL_EXEC, STATE_TOOL_EXEC),
        (STATE_FALLBACK, STATE_FALLBACK),
    ]

    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE)
    step_index = models.IntegerField()
    state = models.CharField(max_length=32, choices=STATE_CHOICES)
    input_json = models.JSONField(null=True, blank=True)
    output_json = models.JSONField(null=True, blank=True)
    tool_name = models.CharField(max_length=64, null=True, blank=True)
    tool_input = models.JSONField(null=True, blank=True)
    tool_output = models.JSONField(null=True, blank=True)
    policy_result = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

