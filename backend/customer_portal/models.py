import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from .constants import (
    DEFAULT_CURRENCY,
    ORDER_STATUS_CHOICES,
    PAYMENT_METHOD_MOCK,
    PAYMENT_STATUS_CHOICES,
    SERVICE_TYPE_CHOICES,
)


class CustomerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    phone = models.CharField(max_length=32, unique=True)
    display_name = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class CustomerAddress(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    contact_name = models.CharField(max_length=64)
    contact_phone = models.CharField(max_length=32)
    address_full = models.TextField()
    door_note = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "is_default"]),
            models.Index(fields=["user", "created_at"]),
        ]


class CustomerCartItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    sku = models.CharField(max_length=32)
    quantity = models.PositiveIntegerField(default=1)
    selected = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "sku"], name="portal_cart_user_sku_uniq"),
        ]
        indexes = [
            models.Index(fields=["user", "selected", "updated_at"]),
            models.Index(fields=["user", "updated_at"]),
        ]


class Order(models.Model):
    order_no = models.CharField(max_length=32, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    service_type = models.CharField(max_length=64, choices=SERVICE_TYPE_CHOICES)
    status = models.CharField(max_length=32, choices=ORDER_STATUS_CHOICES)
    eta_start = models.DateTimeField()
    eta_end = models.DateTimeField()
    cancel_deadline = models.DateTimeField()
    address_edit_deadline = models.DateTimeField()
    is_urgent = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    amount_subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    amount_urgent_fee = models.DecimalField(max_digits=10, decimal_places=2)
    amount_total = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=8, default=DEFAULT_CURRENCY)
    address_snapshot = models.JSONField()
    contact_snapshot = models.JSONField()
    service_payload = models.JSONField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["user", "status", "created_at"]),
            models.Index(fields=["order_no"]),
        ]


class PaymentTransaction(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    status = models.CharField(max_length=16, choices=PAYMENT_STATUS_CHOICES)
    method = models.CharField(max_length=16, default=PAYMENT_METHOD_MOCK)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["order", "created_at"]),
            models.Index(fields=["order", "status"]),
        ]


class OrderEvent(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    event_type = models.CharField(max_length=64)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["order", "created_at"]),
            models.Index(fields=["event_type", "created_at"]),
        ]


class SmsVerification(models.Model):
    PURPOSE_REGISTER = "REGISTER"
    PURPOSE_RESET = "RESET"

    PURPOSE_CHOICES = [
        (PURPOSE_REGISTER, PURPOSE_REGISTER),
        (PURPOSE_RESET, PURPOSE_RESET),
    ]

    phone = models.CharField(max_length=32)
    code = models.CharField(max_length=8)
    purpose = models.CharField(max_length=16, choices=PURPOSE_CHOICES)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def create_code(cls, phone, purpose, ttl_minutes=10):
        code = f"{secrets.randbelow(1000000):06d}"
        return cls.objects.create(
            phone=phone,
            code=code,
            purpose=purpose,
            expires_at=timezone.now() + timedelta(minutes=ttl_minutes),
        )


class CustomerAuthToken(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def rotate_token(cls, user):
        cls.objects.filter(user=user).delete()
        token = secrets.token_hex(24)
        return cls.objects.create(user=user, token=token)


class CustomerFeedback(models.Model):
    TYPE_COMPLAINT = "COMPLAINT"
    TYPE_SUGGESTION = "SUGGESTION"
    TYPE_CHOICES = [
        (TYPE_COMPLAINT, TYPE_COMPLAINT),
        (TYPE_SUGGESTION, TYPE_SUGGESTION),
    ]

    TARGET_ONLINE = "ONLINE_SERVICE"
    TARGET_ORDER = "ORDER_SERVICE"
    TARGET_CHOICES = [
        (TARGET_ONLINE, TARGET_ONLINE),
        (TARGET_ORDER, TARGET_ORDER),
    ]

    STATUS_NEW = "NEW"
    STATUS_PROCESSING = "PROCESSING"
    STATUS_CLOSED = "CLOSED"
    STATUS_CHOICES = [
        (STATUS_NEW, STATUS_NEW),
        (STATUS_PROCESSING, STATUS_PROCESSING),
        (STATUS_CLOSED, STATUS_CLOSED),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True)
    feedback_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    target_type = models.CharField(max_length=24, choices=TARGET_CHOICES)
    title = models.CharField(max_length=120)
    content = models.TextField()
    contact_phone = models.CharField(max_length=32, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_NEW)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["feedback_type", "created_at"]),
            models.Index(fields=["target_type", "created_at"]),
        ]


class CustomerModelProviderProfile(models.Model):
    PROVIDER_OPENAI_COMPAT = "OPENAI_COMPAT"
    PROVIDER_CHOICES = [
        (PROVIDER_OPENAI_COMPAT, PROVIDER_OPENAI_COMPAT),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=64)
    provider_type = models.CharField(
        max_length=32,
        choices=PROVIDER_CHOICES,
        default=PROVIDER_OPENAI_COMPAT,
    )
    api_base_url = models.CharField(max_length=255)
    model_name = models.CharField(max_length=128)
    api_key_ciphertext = models.TextField()
    api_key_masked = models.CharField(max_length=64)
    is_active = models.BooleanField(default=False)
    extra_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="portal_provider_profile_user_name_uniq"),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_active=True),
                name="portal_provider_profile_single_active_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["user", "updated_at"]),
        ]


class CustomerChatPreference(models.Model):
    STYLE_NEUTRAL = "neutral"
    STYLE_WARM = "warm"
    STYLE_DIRECT = "direct"
    STYLE_CHOICES = [
        (STYLE_NEUTRAL, "neutral"),
        (STYLE_WARM, "warm"),
        (STYLE_DIRECT, "direct"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    tone_style = models.CharField(max_length=16, choices=STYLE_CHOICES, default=STYLE_NEUTRAL)
    updated_at = models.DateTimeField(auto_now=True)


class CustomerConversationMemory(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    memory_json = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class CustomerChatMessage(models.Model):
    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_CHOICES = [
        (ROLE_USER, ROLE_USER),
        (ROLE_ASSISTANT, ROLE_ASSISTANT),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    content = models.TextField()
    run_id = models.UUIDField(null=True, blank=True)
    meta_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["user", "run_id", "created_at"]),
        ]


class CustomerNotification(models.Model):
    CATEGORY_ORDER = "ORDER"
    CATEGORY_PAYMENT = "PAYMENT"
    CATEGORY_ADDRESS = "ADDRESS"
    CATEGORY_FEEDBACK = "FEEDBACK"
    CATEGORY_PROFILE = "PROFILE"
    CATEGORY_CHOICES = [
        (CATEGORY_ORDER, CATEGORY_ORDER),
        (CATEGORY_PAYMENT, CATEGORY_PAYMENT),
        (CATEGORY_ADDRESS, CATEGORY_ADDRESS),
        (CATEGORY_FEEDBACK, CATEGORY_FEEDBACK),
        (CATEGORY_PROFILE, CATEGORY_PROFILE),
    ]

    LEVEL_INFO = "INFO"
    LEVEL_SUCCESS = "SUCCESS"
    LEVEL_WARNING = "WARNING"
    LEVEL_ERROR = "ERROR"
    LEVEL_CHOICES = [
        (LEVEL_INFO, LEVEL_INFO),
        (LEVEL_SUCCESS, LEVEL_SUCCESS),
        (LEVEL_WARNING, LEVEL_WARNING),
        (LEVEL_ERROR, LEVEL_ERROR),
    ]

    TARGET_ORDER = "ORDER"
    TARGET_FEEDBACK = "FEEDBACK"
    TARGET_PROFILE = "PROFILE"
    TARGET_ADDRESS = "ADDRESS"
    TARGET_CHAT = "CHAT"
    TARGET_NONE = "NONE"
    TARGET_CHOICES = [
        (TARGET_ORDER, TARGET_ORDER),
        (TARGET_FEEDBACK, TARGET_FEEDBACK),
        (TARGET_PROFILE, TARGET_PROFILE),
        (TARGET_ADDRESS, TARGET_ADDRESS),
        (TARGET_CHAT, TARGET_CHAT),
        (TARGET_NONE, TARGET_NONE),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES)
    event_code = models.CharField(max_length=64)
    title = models.CharField(max_length=120)
    content = models.TextField()
    level = models.CharField(max_length=16, choices=LEVEL_CHOICES, default=LEVEL_INFO)
    is_read = models.BooleanField(default=False)
    target_type = models.CharField(max_length=16, choices=TARGET_CHOICES, default=TARGET_NONE)
    target_id = models.IntegerField(null=True, blank=True)
    target_route = models.CharField(max_length=255, blank=True)
    meta_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "is_read", "created_at"]),
            models.Index(fields=["user", "created_at"]),
        ]
