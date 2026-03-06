from datetime import datetime

from django.contrib.auth import authenticate
from rest_framework import serializers

from .auth_helpers import is_valid_phone, normalize_phone
from .constants import (
    ACCESSORY_CATALOG,
    ACCESSORY_SKUS,
    DELIVERY_PRICES,
    ORDER_STATUS_LABELS,
    SERVICE_TYPE_ACCESSORIES,
    SERVICE_TYPE_CYLINDER_EXCHANGE,
    SERVICE_TYPE_INSTALLATION,
    SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
    SERVICE_TYPE_REPAIR,
    SERVICE_TYPE_SAFETY_CHECK,
    SERVICE_TYPE_CHOICES,
    SERVICE_TYPE_LABELS,
)
from .models import (
    CustomerAddress,
    CustomerCartItem,
    CustomerChatMessage,
    CustomerFeedback,
    CustomerModelProviderProfile,
    CustomerNotification,
    CustomerProfile,
    Order,
    OrderEvent,
)


class SmsRequestSerializer(serializers.Serializer):
    phone = serializers.CharField()
    purpose = serializers.CharField(required=False, allow_blank=True)


class RegisterSerializer(serializers.Serializer):
    phone = serializers.CharField()
    password = serializers.CharField()
    sms_code = serializers.CharField()
    display_name = serializers.CharField(required=False, allow_blank=True)


class LoginSerializer(serializers.Serializer):
    phone = serializers.CharField()
    password = serializers.CharField()

    def validate(self, attrs):
        phone = normalize_phone(attrs.get("phone"))
        password = attrs.get("password")
        if not is_valid_phone(phone):
            raise serializers.ValidationError({"phone": "invalid"})
        user = authenticate(username=phone, password=password)
        if not user:
            raise serializers.ValidationError("invalid_credentials")
        attrs["phone"] = phone
        attrs["user"] = user
        return attrs


class CustomerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerProfile
        fields = ["id", "phone", "display_name", "created_at"]


class ProfileUpdateSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=64)


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField(min_length=8)
    confirm_password = serializers.CharField()

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "not_match"})
        if attrs["old_password"] == attrs["new_password"]:
            raise serializers.ValidationError({"new_password": "same_as_old"})
        return attrs


class CustomerAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerAddress
        fields = [
            "id",
            "contact_name",
            "contact_phone",
            "address_full",
            "door_note",
            "is_default",
            "created_at",
        ]


class AddressCreateUpdateSerializer(serializers.ModelSerializer):
    def validate_contact_phone(self, value):
        phone = normalize_phone(value)
        if not is_valid_phone(phone):
            raise serializers.ValidationError("invalid_cn_phone")
        return phone

    class Meta:
        model = CustomerAddress
        fields = ["contact_name", "contact_phone", "address_full", "door_note", "is_default"]


class CustomerCartItemSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()
    amount = serializers.SerializerMethodField()

    def get_name(self, obj):
        return (ACCESSORY_CATALOG.get(obj.sku) or {}).get("name", obj.sku)

    def get_category(self, obj):
        return (ACCESSORY_CATALOG.get(obj.sku) or {}).get("category", "配件")

    def get_price(self, obj):
        price = (ACCESSORY_CATALOG.get(obj.sku) or {}).get("price")
        return f"{price:.2f}" if price is not None else "0.00"

    def get_amount(self, obj):
        price = (ACCESSORY_CATALOG.get(obj.sku) or {}).get("price")
        if price is None:
            return "0.00"
        return f"{(price * obj.quantity):.2f}"

    class Meta:
        model = CustomerCartItem
        fields = [
            "sku",
            "name",
            "category",
            "quantity",
            "price",
            "amount",
            "updated_at",
        ]


class CartItemUpsertSerializer(serializers.Serializer):
    sku = serializers.ChoiceField(choices=[(sku, sku) for sku in ACCESSORY_SKUS.keys()])
    quantity = serializers.IntegerField(min_value=0, max_value=99)


class OrderEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderEvent
        fields = ["event_type", "payload", "created_at"]


class OrderSerializer(serializers.ModelSerializer):
    service_type_label = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    events = serializers.SerializerMethodField()
    assigned_worker = serializers.SerializerMethodField()

    def get_service_type_label(self, obj):
        return SERVICE_TYPE_LABELS.get(obj.service_type, obj.service_type)

    def get_status_label(self, obj):
        return ORDER_STATUS_LABELS.get(obj.status, obj.status)

    def get_events(self, obj):
        events = OrderEvent.objects.filter(order=obj).order_by("-created_at")
        return OrderEventSerializer(events, many=True).data

    def get_assigned_worker(self, obj):
        payload = obj.service_payload if isinstance(obj.service_payload, dict) else {}
        worker = payload.get("assigned_worker") if isinstance(payload.get("assigned_worker"), dict) else {}
        return {
            "name": worker.get("name") or "",
            "phone": worker.get("phone") or "",
        }

    class Meta:
        model = Order
        fields = [
            "id",
            "order_no",
            "service_type",
            "service_type_label",
            "status",
            "status_label",
            "eta_start",
            "eta_end",
            "cancel_deadline",
            "address_edit_deadline",
            "is_urgent",
            "notes",
            "amount_subtotal",
            "amount_urgent_fee",
            "amount_total",
            "currency",
            "address_snapshot",
            "contact_snapshot",
            "service_payload",
            "assigned_worker",
            "expires_at",
            "created_at",
            "updated_at",
            "events",
        ]


class OrderListSerializer(serializers.ModelSerializer):
    service_type_label = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    assigned_worker = serializers.SerializerMethodField()

    def get_service_type_label(self, obj):
        return SERVICE_TYPE_LABELS.get(obj.service_type, obj.service_type)

    def get_status_label(self, obj):
        return ORDER_STATUS_LABELS.get(obj.status, obj.status)

    def get_assigned_worker(self, obj):
        payload = obj.service_payload if isinstance(obj.service_payload, dict) else {}
        worker = payload.get("assigned_worker") if isinstance(payload.get("assigned_worker"), dict) else {}
        return {
            "name": worker.get("name") or "",
            "phone": worker.get("phone") or "",
        }

    class Meta:
        model = Order
        fields = [
            "id",
            "order_no",
            "service_type",
            "service_type_label",
            "status",
            "status_label",
            "eta_start",
            "eta_end",
            "amount_total",
            "currency",
            "assigned_worker",
            "created_at",
        ]


class OrderCreateSerializer(serializers.Serializer):
    service_type = serializers.ChoiceField(choices=SERVICE_TYPE_CHOICES)
    service_payload = serializers.JSONField()
    contact_name = serializers.CharField(required=False, allow_blank=True)
    contact_phone = serializers.CharField(required=False, allow_blank=True)
    address_full = serializers.CharField(required=False, allow_blank=True)
    door_note = serializers.CharField(required=False, allow_blank=True)
    address_id = serializers.IntegerField(required=False)
    eta_window = serializers.CharField(required=False, allow_blank=True)
    eta_date = serializers.CharField(required=False, allow_blank=True)
    eta_slot = serializers.CharField(required=False, allow_blank=True)
    is_urgent = serializers.BooleanField(required=False, default=False)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        contact_phone = normalize_phone(attrs.get("contact_phone"))
        if contact_phone:
            if not is_valid_phone(contact_phone):
                raise serializers.ValidationError({"contact_phone": "invalid_cn_phone"})
            attrs["contact_phone"] = contact_phone

        address_id = attrs.get("address_id")
        if not address_id:
            missing = []
            for field in ["contact_name", "contact_phone", "address_full"]:
                if not attrs.get(field):
                    missing.append(field)
            if missing:
                raise serializers.ValidationError({field: "required" for field in missing})

        service_type = attrs.get("service_type")
        payload = attrs.get("service_payload") or {}
        if not isinstance(payload, dict):
            raise serializers.ValidationError({"service_payload": "invalid"})
        errors = {}

        def _require(field_name):
            if not payload.get(field_name):
                errors[field_name] = "required"

        if service_type in {SERVICE_TYPE_LPG_CYLINDER_DELIVERY, SERVICE_TYPE_CYLINDER_EXCHANGE}:
            _require("cylinder_type")
            _require("quantity")
            cylinder_type = payload.get("cylinder_type")
            if cylinder_type and cylinder_type not in DELIVERY_PRICES:
                errors["cylinder_type"] = "invalid"
            quantity = payload.get("quantity")
            if quantity is not None:
                try:
                    quantity = int(quantity)
                    if quantity < 1:
                        errors["quantity"] = "invalid"
                except (TypeError, ValueError):
                    errors["quantity"] = "invalid"
            if service_type == SERVICE_TYPE_CYLINDER_EXCHANGE:
                if "return_empty" not in payload:
                    errors["return_empty"] = "required"
        elif service_type == SERVICE_TYPE_INSTALLATION:
            _require("install_item")
        elif service_type == SERVICE_TYPE_SAFETY_CHECK:
            _require("check_scope")
        elif service_type == SERVICE_TYPE_REPAIR:
            _require("issue_desc")
        elif service_type == SERVICE_TYPE_ACCESSORIES:
            items = payload.get("items")
            if not items or not isinstance(items, list):
                errors["items"] = "required"
            else:
                for index, item in enumerate(items):
                    sku = item.get("sku")
                    qty = item.get("quantity")
                    if sku not in ACCESSORY_SKUS:
                        errors[f"items[{index}].sku"] = "invalid"
                    try:
                        qty = int(qty)
                        if qty < 1:
                            errors[f"items[{index}].quantity"] = "invalid"
                    except (TypeError, ValueError):
                        errors[f"items[{index}].quantity"] = "invalid"
        else:
            errors["service_type"] = "invalid"

        if errors:
            raise serializers.ValidationError(errors)

        eta_date = attrs.get("eta_date") or ""
        eta_slot = attrs.get("eta_slot") or ""
        if (eta_date and not eta_slot) or (eta_slot and not eta_date):
            raise serializers.ValidationError(
                {"eta_date": "required_with_eta_slot", "eta_slot": "required_with_eta_date"}
            )
        if eta_date:
            try:
                datetime.strptime(eta_date, "%Y-%m-%d")
            except ValueError:
                raise serializers.ValidationError({"eta_date": "invalid"})
        if eta_slot and "-" not in eta_slot:
            raise serializers.ValidationError({"eta_slot": "invalid"})
        return attrs


class OrderModifyAddressSerializer(serializers.Serializer):
    address_id = serializers.IntegerField(required=False)
    contact_name = serializers.CharField(required=False, allow_blank=True)
    contact_phone = serializers.CharField(required=False, allow_blank=True)
    address_full = serializers.CharField(required=False, allow_blank=True)
    door_note = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        contact_phone = normalize_phone(attrs.get("contact_phone"))
        if contact_phone:
            if not is_valid_phone(contact_phone):
                raise serializers.ValidationError({"contact_phone": "invalid_cn_phone"})
            attrs["contact_phone"] = contact_phone

        if not attrs.get("address_id"):
            missing = []
            for field in ["contact_name", "contact_phone", "address_full"]:
                if not attrs.get(field):
                    missing.append(field)
            if missing:
                raise serializers.ValidationError({field: "required" for field in missing})
        return attrs


class FeedbackCreateSerializer(serializers.Serializer):
    feedback_type = serializers.ChoiceField(choices=CustomerFeedback.TYPE_CHOICES)
    target_type = serializers.ChoiceField(choices=CustomerFeedback.TARGET_CHOICES)
    title = serializers.CharField(max_length=120)
    content = serializers.CharField()
    contact_phone = serializers.CharField(required=False, allow_blank=True)
    order_id = serializers.IntegerField(required=False)

    def validate(self, attrs):
        contact_phone = normalize_phone(attrs.get("contact_phone"))
        if contact_phone:
            if not is_valid_phone(contact_phone):
                raise serializers.ValidationError({"contact_phone": "invalid_cn_phone"})
            attrs["contact_phone"] = contact_phone

        target_type = attrs.get("target_type")
        order_id = attrs.get("order_id")
        if target_type == CustomerFeedback.TARGET_ORDER and not order_id:
            raise serializers.ValidationError({"order_id": "required"})
        if target_type == CustomerFeedback.TARGET_ONLINE:
            attrs.pop("order_id", None)
        return attrs


class FeedbackSerializer(serializers.ModelSerializer):
    order_no = serializers.SerializerMethodField()

    def get_order_no(self, obj):
        return obj.order.order_no if obj.order else ""

    class Meta:
        model = CustomerFeedback
        fields = [
            "id",
            "feedback_type",
            "target_type",
            "title",
            "content",
            "contact_phone",
            "status",
            "order_no",
            "created_at",
            "updated_at",
        ]


class LlmProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerModelProviderProfile
        fields = [
            "id",
            "name",
            "provider_type",
            "api_base_url",
            "model_name",
            "api_key_masked",
            "is_active",
            "extra_json",
            "created_at",
            "updated_at",
        ]


class LlmProfileCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=64)
    provider_type = serializers.ChoiceField(choices=CustomerModelProviderProfile.PROVIDER_CHOICES)
    api_base_url = serializers.CharField(max_length=255)
    api_key = serializers.CharField(required=False, allow_blank=True)
    model_name = serializers.CharField(max_length=128)
    is_active = serializers.BooleanField(required=False)
    extra_json = serializers.JSONField(required=False)

    def validate_api_base_url(self, value):
        base = (value or "").strip().rstrip("/")
        if not base or not (base.startswith("http://") or base.startswith("https://")):
            raise serializers.ValidationError("invalid")
        return base

    def validate_api_key(self, value):
        return (value or "").strip()

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("required")
        return name

    def validate_model_name(self, value):
        model = (value or "").strip()
        if not model:
            raise serializers.ValidationError("required")
        return model


class LlmProfileUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=64, required=False)
    provider_type = serializers.ChoiceField(
        choices=CustomerModelProviderProfile.PROVIDER_CHOICES, required=False
    )
    api_base_url = serializers.CharField(max_length=255, required=False)
    api_key = serializers.CharField(required=False, allow_blank=True)
    model_name = serializers.CharField(max_length=128, required=False)
    is_active = serializers.BooleanField(required=False)
    extra_json = serializers.JSONField(required=False)

    def validate_api_base_url(self, value):
        base = (value or "").strip().rstrip("/")
        if not base or not (base.startswith("http://") or base.startswith("https://")):
            raise serializers.ValidationError("invalid")
        return base

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("required")
        return name

    def validate_model_name(self, value):
        model = (value or "").strip()
        if not model:
            raise serializers.ValidationError("required")
        return model


class CustomerChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerChatMessage
        fields = ["id", "role", "content", "run_id", "created_at"]


class CustomerNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerNotification
        fields = [
            "id",
            "category",
            "event_code",
            "title",
            "content",
            "level",
            "is_read",
            "target_type",
            "target_id",
            "target_route",
            "meta_json",
            "created_at",
            "read_at",
        ]
