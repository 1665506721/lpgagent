import json
import urllib.error
import urllib.request

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView

from .auth import get_authenticated_user
from .auth_helpers import ensure_test_account, is_valid_phone, normalize_phone
from .constants import ORDER_STATUS_CHOICES, ORDER_STATUS_PENDING_PAYMENT, TEST_ACCOUNT_PHONE
from .models import (
    CustomerAddress,
    CustomerAuthToken,
    CustomerChatMessage,
    CustomerConversationMemory,
    CustomerFeedback,
    CustomerModelProviderProfile,
    CustomerNotification,
    CustomerProfile,
    Order,
    SmsVerification,
)
from .notifications import create_notification, mark_all_read, mark_read
from .response import error_response, ok_response
from .security import decrypt_api_key, encrypt_api_key, mask_api_key
from .serializers import (
    AddressCreateUpdateSerializer,
    CartItemUpsertSerializer,
    ChangePasswordSerializer,
    CustomerAddressSerializer,
    CustomerChatMessageSerializer,
    CustomerNotificationSerializer,
    CustomerProfileSerializer,
    FeedbackCreateSerializer,
    FeedbackSerializer,
    LlmProfileCreateSerializer,
    LlmProfileSerializer,
    LlmProfileUpdateSerializer,
    LoginSerializer,
    OrderCreateSerializer,
    OrderListSerializer,
    OrderModifyAddressSerializer,
    OrderSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    SmsRequestSerializer,
)
from .service_catalog import get_service_form, list_services
from .services import (
    apply_expiration_if_needed,
    cart_summary,
    cancel_order,
    checkout_cart,
    clear_cart_items,
    create_order,
    get_now,
    remove_cart_items,
    set_cart_item,
    modify_order_address,
    pay_order,
)


User = get_user_model()


def _auth_required(request):
    user = get_authenticated_user(request)
    if not user:
        return None, error_response("AUTH_REQUIRED", "请先登录", status_code=401)
    return user, None


def _active_profile(user):
    return (
        CustomerModelProviderProfile.objects.filter(user=user, is_active=True)
        .order_by("-updated_at", "-id")
        .first()
    )


def _activate_profile(user, profile):
    CustomerModelProviderProfile.objects.filter(user=user, is_active=True).exclude(id=profile.id).update(
        is_active=False
    )
    if not profile.is_active:
        profile.is_active = True
        profile.save(update_fields=["is_active", "updated_at"])


def _profile_not_found_response():
    return error_response(
        "PROVIDER_PROFILE_NOT_FOUND",
        "provider profile not found",
        status_code=status.HTTP_404_NOT_FOUND,
    )


def _encryption_config_error_response(exc):
    return error_response(
        "ENCRYPTION_CONFIG_ERROR",
        "encryption config error",
        details={"detail": str(exc)},
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _provider_config_invalid_response(details=None):
    return error_response(
        "PROVIDER_CONFIG_INVALID",
        "provider config invalid",
        details=details or {},
        status_code=status.HTTP_400_BAD_REQUEST,
    )


def _profile_for_user(user, profile_id):
    return CustomerModelProviderProfile.objects.filter(id=profile_id, user=user).first()


def _profile_with_permission(user, profile_id):
    profile = CustomerModelProviderProfile.objects.filter(id=profile_id).first()
    if not profile:
        return None, _profile_not_found_response()
    if profile.user_id != user.id:
        return (
            None,
            error_response(
                "PROVIDER_PROFILE_FORBIDDEN",
                "provider profile forbidden",
                status_code=status.HTTP_403_FORBIDDEN,
            ),
        )
    return profile, None


def _to_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _normalize_provider_models(payload):
    records = []
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            records = data
    elif isinstance(payload, list):
        records = payload

    result = []
    seen = set()
    for item in records:
        model_id = ""
        if isinstance(item, str):
            model_id = item.strip()
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("model") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        result.append({"id": model_id, "label": model_id})
    return result


def _fetch_models_by_profile(profile):
    api_key = decrypt_api_key(profile.api_key_ciphertext)
    url = f"{profile.api_base_url.rstrip('/')}/models"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        text = response.read().decode("utf-8")
    payload = json.loads(text) if text else {}
    return _normalize_provider_models(payload)


class SmsRequestView(APIView):
    def post(self, request):
        serializer = SmsRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                "VALIDATION_ERROR",
                "invalid payload",
                serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        phone = normalize_phone(serializer.validated_data["phone"])
        if not is_valid_phone(phone):
            return error_response(
                "VALIDATION_ERROR",
                "invalid phone",
                {"phone": "invalid"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        purpose = serializer.validated_data.get("purpose") or SmsVerification.PURPOSE_REGISTER
        if purpose not in {SmsVerification.PURPOSE_REGISTER, SmsVerification.PURPOSE_RESET}:
            return error_response(
                "VALIDATION_ERROR",
                "invalid purpose",
                {"purpose": "invalid"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        verification = SmsVerification.create_code(phone, purpose)
        return ok_response(
            {
                "phone": phone,
                "code": verification.code,
                "purpose": purpose,
                "expires_at": verification.expires_at.isoformat(),
            }
        )


class RegisterView(APIView):
    @transaction.atomic
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                "VALIDATION_ERROR",
                "invalid payload",
                serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        phone = normalize_phone(serializer.validated_data["phone"])
        password = serializer.validated_data["password"]
        sms_code = serializer.validated_data["sms_code"]
        display_name = serializer.validated_data.get("display_name", "").strip()

        if not is_valid_phone(phone):
            return error_response(
                "VALIDATION_ERROR",
                "invalid phone",
                {"phone": "invalid"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if User.objects.filter(username=phone).exists():
            return error_response(
                "VALIDATION_ERROR",
                "phone already registered",
                {"phone": "exists"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        verification = (
            SmsVerification.objects.filter(
                phone=phone,
                code=sms_code,
                purpose=SmsVerification.PURPOSE_REGISTER,
                is_used=False,
                expires_at__gt=timezone.now(),
            )
            .order_by("-created_at")
            .first()
        )
        if not verification:
            return error_response(
                "VALIDATION_ERROR",
                "invalid sms code",
                {"sms_code": "invalid"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.create_user(username=phone, password=password)
        profile = CustomerProfile.objects.create(
            user=user,
            phone=phone,
            display_name=display_name or phone,
        )
        verification.is_used = True
        verification.save(update_fields=["is_used"])
        token = CustomerAuthToken.rotate_token(user)
        return ok_response(
            {"token": token.token, "profile": CustomerProfileSerializer(profile).data},
            status_code=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    def post(self, request):
        phone = normalize_phone(request.data.get("phone"))
        if phone == TEST_ACCOUNT_PHONE:
            ensure_test_account()
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            message = "invalid credentials"
            details = serializer.errors
            return error_response(
                "VALIDATION_ERROR",
                message,
                details,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        user = serializer.validated_data["user"]
        profile, _ = CustomerProfile.objects.get_or_create(
            user=user,
            defaults={"phone": user.username, "display_name": user.username},
        )
        token = CustomerAuthToken.rotate_token(user)
        return ok_response({"token": token.token, "profile": CustomerProfileSerializer(profile).data})


class MeView(APIView):
    def get(self, request):
        user, error = _auth_required(request)
        if error:
            return error
        profile, _ = CustomerProfile.objects.get_or_create(
            user=user,
            defaults={"phone": user.username, "display_name": user.username},
        )
        return ok_response(CustomerProfileSerializer(profile).data)

    def put(self, request):
        user, error = _auth_required(request)
        if error:
            return error
        serializer = ProfileUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                "VALIDATION_ERROR",
                "invalid payload",
                serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        profile, _ = CustomerProfile.objects.get_or_create(
            user=user,
            defaults={"phone": user.username, "display_name": user.username},
        )
        profile.display_name = serializer.validated_data["display_name"].strip() or profile.phone
        profile.save(update_fields=["display_name"])
        create_notification(
            user=user,
            category=CustomerNotification.CATEGORY_PROFILE,
            event_code="PROFILE_UPDATED",
            title="个人资料已更新",
            content=f"您的昵称已更新为 {profile.display_name}。",
            level=CustomerNotification.LEVEL_INFO,
            target_type=CustomerNotification.TARGET_PROFILE,
            target_route="#/portal/profile",
            meta_json={"display_name": profile.display_name},
        )
        return ok_response(CustomerProfileSerializer(profile).data)


class MePasswordView(APIView):
    def post(self, request):
        user, error = _auth_required(request)
        if error:
            return error
        serializer = ChangePasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                "VALIDATION_ERROR",
                "invalid payload",
                serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        old_password = serializer.validated_data["old_password"]
        new_password = serializer.validated_data["new_password"]
        if not user.check_password(old_password):
            return error_response(
                "VALIDATION_ERROR",
                "old password invalid",
                {"old_password": "invalid"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        user.set_password(new_password)
        user.save(update_fields=["password"])
        token = CustomerAuthToken.rotate_token(user)
        create_notification(
            user=user,
            category=CustomerNotification.CATEGORY_PROFILE,
            event_code="PASSWORD_CHANGED",
            title="登录密码已修改",
            content="您的登录密码已修改成功。",
            level=CustomerNotification.LEVEL_INFO,
            target_type=CustomerNotification.TARGET_PROFILE,
            target_route="#/portal/profile",
        )
        return ok_response({"token": token.token})


class AddressListCreateView(APIView):
    def get(self, request):
        user, error = _auth_required(request)
        if error:
            return error
        addresses = CustomerAddress.objects.filter(user=user).order_by("-is_default", "-created_at")
        return ok_response(CustomerAddressSerializer(addresses, many=True).data)

    def post(self, request):
        user, error = _auth_required(request)
        if error:
            return error
        serializer = AddressCreateUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                "VALIDATION_ERROR",
                "invalid payload",
                serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        is_default = serializer.validated_data.get("is_default", False)
        if not CustomerAddress.objects.filter(user=user).exists():
            is_default = True
        address = serializer.save(user=user, is_default=is_default)
        if is_default:
            CustomerAddress.objects.filter(user=user).exclude(id=address.id).update(is_default=False)
        create_notification(
            user=user,
            category=CustomerNotification.CATEGORY_ADDRESS,
            event_code="ADDRESS_CREATED",
            title="地址已新增",
            content=f"已新增地址：{address.address_full}",
            level=CustomerNotification.LEVEL_INFO,
            target_type=CustomerNotification.TARGET_ADDRESS,
            target_id=address.id,
            target_route="#/portal/profile",
            meta_json={"address_id": address.id},
        )
        return ok_response(CustomerAddressSerializer(address).data, status_code=status.HTTP_201_CREATED)


class AddressDetailView(APIView):
    def put(self, request, address_id):
        user, error = _auth_required(request)
        if error:
            return error
        address = CustomerAddress.objects.filter(id=address_id, user=user).first()
        if not address:
            return error_response(
                "VALIDATION_ERROR",
                "address not found",
                {"address_id": "not_found"},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        serializer = AddressCreateUpdateSerializer(address, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response(
                "VALIDATION_ERROR",
                "invalid payload",
                serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        is_default = serializer.validated_data.get("is_default", address.is_default)
        address = serializer.save(is_default=is_default)
        if is_default:
            CustomerAddress.objects.filter(user=user).exclude(id=address.id).update(is_default=False)
        create_notification(
            user=user,
            category=CustomerNotification.CATEGORY_ADDRESS,
            event_code="ADDRESS_UPDATED",
            title="地址已更新",
            content=f"地址已更新为：{address.address_full}",
            level=CustomerNotification.LEVEL_INFO,
            target_type=CustomerNotification.TARGET_ADDRESS,
            target_id=address.id,
            target_route="#/portal/profile",
            meta_json={"address_id": address.id},
        )
        return ok_response(CustomerAddressSerializer(address).data)

    def delete(self, request, address_id):
        user, error = _auth_required(request)
        if error:
            return error
        address = CustomerAddress.objects.filter(id=address_id, user=user).first()
        if not address:
            return error_response(
                "VALIDATION_ERROR",
                "address not found",
                {"address_id": "not_found"},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        deleted_id = address.id
        was_default = address.is_default
        address.delete()
        if was_default:
            next_default = CustomerAddress.objects.filter(user=user).order_by("-created_at").first()
            if next_default:
                CustomerAddress.objects.filter(user=user).exclude(id=next_default.id).update(is_default=False)
                next_default.is_default = True
                next_default.save(update_fields=["is_default"])
        return ok_response({"deleted_id": deleted_id})


class AddressDefaultView(APIView):
    def post(self, request, address_id):
        user, error = _auth_required(request)
        if error:
            return error
        address = CustomerAddress.objects.filter(id=address_id, user=user).first()
        if not address:
            return error_response(
                "VALIDATION_ERROR",
                "address not found",
                {"address_id": "not_found"},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        CustomerAddress.objects.filter(user=user).update(is_default=False)
        address.is_default = True
        address.save(update_fields=["is_default"])
        create_notification(
            user=user,
            category=CustomerNotification.CATEGORY_ADDRESS,
            event_code="ADDRESS_SET_DEFAULT",
            title="默认地址已更新",
            content=f"已将默认地址设置为：{address.address_full}",
            level=CustomerNotification.LEVEL_INFO,
            target_type=CustomerNotification.TARGET_ADDRESS,
            target_id=address.id,
            target_route="#/portal/profile",
            meta_json={"address_id": address.id},
        )
        return ok_response(CustomerAddressSerializer(address).data)


class CartItemListCreateView(APIView):
    def get(self, request):
        user, error = _auth_required(request)
        if error:
            return error
        return ok_response(cart_summary(user))

    def post(self, request):
        user, error = _auth_required(request)
        if error:
            return error
        serializer = CartItemUpsertSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                "VALIDATION_ERROR",
                "invalid payload",
                serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        data = serializer.validated_data
        try:
            set_cart_item(user, data["sku"], data["quantity"])
        except ValueError as exc:
            return error_response(
                "VALIDATION_ERROR",
                "invalid payload",
                {"detail": str(exc)},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return ok_response(cart_summary(user))


class CartItemDetailView(APIView):
    def put(self, request, sku):
        user, error = _auth_required(request)
        if error:
            return error
        payload = {"sku": (sku or "").upper(), "quantity": request.data.get("quantity")}
        serializer = CartItemUpsertSerializer(data=payload)
        if not serializer.is_valid():
            return error_response(
                "VALIDATION_ERROR",
                "invalid payload",
                serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        data = serializer.validated_data
        try:
            set_cart_item(user, data["sku"], data["quantity"])
        except ValueError as exc:
            return error_response(
                "VALIDATION_ERROR",
                "invalid payload",
                {"detail": str(exc)},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return ok_response(cart_summary(user))

    def delete(self, request, sku):
        user, error = _auth_required(request)
        if error:
            return error
        try:
            remove_cart_items(user, [{"sku": (sku or "").upper()}])
        except ValueError as exc:
            return error_response(
                "VALIDATION_ERROR",
                "invalid payload",
                {"detail": str(exc)},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return ok_response(cart_summary(user))


class CartClearView(APIView):
    def post(self, request):
        user, error = _auth_required(request)
        if error:
            return error
        deleted = clear_cart_items(user)
        data = cart_summary(user)
        data["deleted_count"] = deleted
        return ok_response(data)


class CartCheckoutView(APIView):
    def post(self, request):
        user, error = _auth_required(request)
        if error:
            return error
        payload = request.data if isinstance(request.data, dict) else {}
        try:
            order = checkout_cart(
                user,
                address_id=payload.get("address_id"),
                eta_date=payload.get("eta_date"),
                eta_slot=payload.get("eta_slot"),
                is_urgent=bool(payload.get("is_urgent")),
                notes=payload.get("notes") or "",
                invoice_required=bool(payload.get("need_invoice")),
                invoice_title=payload.get("invoice_title") or "",
                invoice_tax_no=payload.get("invoice_tax_no") or "",
                auto_pay=bool(payload.get("auto_pay", True)),
            )
        except ValueError as exc:
            code_map = {
                "cart_empty": "VALIDATION_ERROR",
                "address_required": "VALIDATION_ERROR",
                "ORDER_EXPIRED": "ORDER_EXPIRED",
            }
            code = code_map.get(str(exc), "VALIDATION_ERROR")
            return error_response(
                code,
                "checkout failed",
                {"detail": str(exc)},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return ok_response(OrderSerializer(order).data)


class ServiceListView(APIView):
    def get(self, request):
        return ok_response(list_services())


class ServiceFormView(APIView):
    def get(self, request, code):
        form = get_service_form(code.upper())
        if not form:
            return error_response(
                "VALIDATION_ERROR",
                "invalid service type",
                {"service_type": "invalid"},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return ok_response(form)


class OrderListCreateView(APIView):
    def get(self, request):
        user, error = _auth_required(request)
        if error:
            return error

        now = get_now()
        expired_candidates = Order.objects.filter(
            user=user,
            status=ORDER_STATUS_PENDING_PAYMENT,
            expires_at__lte=now,
        )
        for item in expired_candidates:
            apply_expiration_if_needed(item, now=now)

        status_filter = request.query_params.get("status")
        if status_filter:
            valid_statuses = {value for value, _ in ORDER_STATUS_CHOICES}
            if status_filter not in valid_statuses:
                return error_response(
                    "VALIDATION_ERROR",
                    "invalid status",
                    {"status": "invalid"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        keyword = (request.query_params.get("keyword") or request.query_params.get("q") or "").strip()

        try:
            page = int(request.query_params.get("page", 1))
            page_size = int(request.query_params.get("page_size", 10))
        except (TypeError, ValueError):
            return error_response(
                "VALIDATION_ERROR",
                "invalid pagination",
                {"page": "invalid"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        page = max(1, page)
        page_size = max(1, min(50, page_size))

        orders = Order.objects.filter(user=user)
        if status_filter:
            orders = orders.filter(status=status_filter)
        if keyword:
            orders = orders.filter(
                Q(order_no__icontains=keyword)
                | Q(service_type__icontains=keyword)
                | Q(notes__icontains=keyword)
            )
        total = orders.count()
        offset = (page - 1) * page_size
        items = orders.order_by("-created_at")[offset : offset + page_size]

        data = {
            "items": OrderListSerializer(items, many=True).data,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "keyword": keyword,
            "status": status_filter or "",
        }
        return ok_response(data)

    def post(self, request):
        user, error = _auth_required(request)
        if error:
            return error
        serializer = OrderCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                "VALIDATION_ERROR",
                "invalid payload",
                serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        address_snapshot = {}
        contact_snapshot = {}

        address_id = data.get("address_id")
        if address_id:
            address = CustomerAddress.objects.filter(id=address_id, user=user).first()
            if not address:
                return error_response(
                    "VALIDATION_ERROR",
                    "address not found",
                    {"address_id": "not_found"},
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            address_snapshot = {
                "address_full": address.address_full,
                "door_note": address.door_note,
            }
            contact_snapshot = {
                "contact_name": data.get("contact_name") or address.contact_name,
                "contact_phone": data.get("contact_phone") or address.contact_phone,
            }
        else:
            address_snapshot = {
                "address_full": data.get("address_full", ""),
                "door_note": data.get("door_note", ""),
            }
            contact_snapshot = {
                "contact_name": data.get("contact_name", ""),
                "contact_phone": data.get("contact_phone", ""),
            }

        try:
            order = create_order(
                user=user,
                service_type=data["service_type"],
                service_payload=data["service_payload"],
                contact_snapshot=contact_snapshot,
                address_snapshot=address_snapshot,
                eta_date=data.get("eta_date"),
                eta_slot=data.get("eta_slot"),
                is_urgent=data.get("is_urgent", False),
                notes=data.get("notes", ""),
            )
        except ValueError as exc:
            return error_response(
                "VALIDATION_ERROR",
                "invalid payload",
                {"detail": str(exc)},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return ok_response(OrderSerializer(order).data, status_code=status.HTTP_201_CREATED)


class OrderPayView(APIView):
    def post(self, request, order_id):
        user, error = _auth_required(request)
        if error:
            return error
        order = Order.objects.filter(id=order_id, user=user).first()
        if not order:
            return error_response(
                "ORDER_NOT_FOUND",
                "order not found",
                {"order_id": "not_found"},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        order, err = pay_order(order)
        if err == "ORDER_EXPIRED":
            return error_response(
                "ORDER_EXPIRED",
                "order expired",
                {"order_id": order_id},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if err:
            return error_response(
                "ORDER_NOT_EDITABLE",
                "order not payable",
                {"order_id": order_id},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return ok_response(OrderSerializer(order).data)


class OrderCancelView(APIView):
    def post(self, request, order_id):
        user, error = _auth_required(request)
        if error:
            return error
        order = Order.objects.filter(id=order_id, user=user).first()
        if not order:
            return error_response(
                "ORDER_NOT_FOUND",
                "order not found",
                {"order_id": "not_found"},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        order, err = cancel_order(order)
        if err == "ORDER_EXPIRED":
            return error_response(
                "ORDER_EXPIRED",
                "order expired",
                {"order_id": order_id},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if err:
            return error_response(
                "ORDER_NOT_CANCELABLE",
                "order not cancelable",
                {"order_id": order_id},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return ok_response(OrderSerializer(order).data)


class OrderModifyAddressView(APIView):
    def post(self, request, order_id):
        user, error = _auth_required(request)
        if error:
            return error
        order = Order.objects.filter(id=order_id, user=user).first()
        if not order:
            return error_response(
                "ORDER_NOT_FOUND",
                "order not found",
                {"order_id": "not_found"},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        serializer = OrderModifyAddressSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                "VALIDATION_ERROR",
                "invalid payload",
                serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        if data.get("address_id"):
            address = CustomerAddress.objects.filter(id=data["address_id"], user=user).first()
            if not address:
                return error_response(
                    "VALIDATION_ERROR",
                    "address not found",
                    {"address_id": "not_found"},
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            address_snapshot = {
                "address_full": address.address_full,
                "door_note": address.door_note,
            }
            contact_snapshot = {
                "contact_name": data.get("contact_name") or address.contact_name,
                "contact_phone": data.get("contact_phone") or address.contact_phone,
            }
        else:
            address_snapshot = {
                "address_full": data.get("address_full", ""),
                "door_note": data.get("door_note", ""),
            }
            contact_snapshot = {
                "contact_name": data.get("contact_name", ""),
                "contact_phone": data.get("contact_phone", ""),
            }

        order, err = modify_order_address(order, address_snapshot, contact_snapshot)
        if err == "ORDER_EXPIRED":
            return error_response(
                "ORDER_EXPIRED",
                "order expired",
                {"order_id": order_id},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if err:
            return error_response(
                "ORDER_NOT_EDITABLE",
                "order not editable",
                {"order_id": order_id},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return ok_response(OrderSerializer(order).data)


class OrderDetailView(APIView):
    def get(self, request, order_id):
        user, error = _auth_required(request)
        if error:
            return error
        order = Order.objects.filter(id=order_id, user=user).first()
        if not order:
            return error_response(
                "ORDER_NOT_FOUND",
                "order not found",
                {"order_id": "not_found"},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        apply_expiration_if_needed(order)
        return ok_response(OrderSerializer(order).data)


class FeedbackListCreateView(APIView):
    def get(self, request):
        user, error = _auth_required(request)
        if error:
            return error

        feedback_type = (request.query_params.get("feedback_type") or "").strip()
        target_type = (request.query_params.get("target_type") or "").strip()

        items = CustomerFeedback.objects.filter(user=user)
        if feedback_type:
            items = items.filter(feedback_type=feedback_type)
        if target_type:
            items = items.filter(target_type=target_type)
        items = items.order_by("-created_at")[:100]
        return ok_response(FeedbackSerializer(items, many=True).data)

    def post(self, request):
        user, error = _auth_required(request)
        if error:
            return error

        serializer = FeedbackCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                "VALIDATION_ERROR",
                "invalid payload",
                serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        order = None
        if data.get("order_id"):
            order = Order.objects.filter(id=data["order_id"], user=user).first()
            if not order:
                return error_response(
                    "ORDER_NOT_FOUND",
                    "order not found",
                    {"order_id": "not_found"},
                    status_code=status.HTTP_404_NOT_FOUND,
                )

        feedback = CustomerFeedback.objects.create(
            user=user,
            order=order,
            feedback_type=data["feedback_type"],
            target_type=data["target_type"],
            title=data["title"].strip(),
            content=data["content"].strip(),
            contact_phone=data.get("contact_phone", ""),
        )
        feedback_label = "投诉" if feedback.feedback_type == CustomerFeedback.TYPE_COMPLAINT else "建议"
        create_notification(
            user=user,
            category=CustomerNotification.CATEGORY_FEEDBACK,
            event_code="FEEDBACK_CREATED",
            title=f"{feedback_label}已提交",
            content=f"{feedback_label}已提交（编号 #{feedback.id}），当前状态：{feedback.status}。",
            level=CustomerNotification.LEVEL_SUCCESS,
            target_type=CustomerNotification.TARGET_FEEDBACK,
            target_id=feedback.id,
            target_route="#/portal/profile",
            meta_json={"feedback_id": feedback.id, "feedback_type": feedback.feedback_type},
        )
        return ok_response(FeedbackSerializer(feedback).data, status_code=status.HTTP_201_CREATED)


class NotificationListView(APIView):
    def get(self, request):
        user, error = _auth_required(request)
        if error:
            return error

        try:
            page = int(request.query_params.get("page", 1))
            page_size = int(request.query_params.get("page_size", 20))
        except (TypeError, ValueError):
            return error_response(
                "VALIDATION_ERROR",
                "invalid pagination",
                {"page": "invalid"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        page = max(1, page)
        page_size = max(1, min(50, page_size))
        only_unread = _to_bool(request.query_params.get("only_unread"), default=False)

        qs = CustomerNotification.objects.filter(user=user)
        unread_count = qs.filter(is_read=False).count()
        if only_unread:
            qs = qs.filter(is_read=False)
        total = qs.count()
        offset = (page - 1) * page_size
        items = qs.order_by("-created_at")[offset : offset + page_size]
        return ok_response(
            {
                "items": CustomerNotificationSerializer(items, many=True).data,
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size,
                "unread_count": unread_count,
                "only_unread": only_unread,
            }
        )


class NotificationReadView(APIView):
    def post(self, request, notification_id):
        user, error = _auth_required(request)
        if error:
            return error
        item = mark_read(user, notification_id)
        if not item:
            return error_response(
                "NOTIFICATION_NOT_FOUND",
                "notification not found",
                {"notification_id": "not_found"},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return ok_response(CustomerNotificationSerializer(item).data)


class NotificationReadAllView(APIView):
    def post(self, request):
        user, error = _auth_required(request)
        if error:
            return error
        updated_count = mark_all_read(user)
        return ok_response({"updated_count": updated_count})


class LlmProfileListCreateView(APIView):
    def get(self, request):
        user, error = _auth_required(request)
        if error:
            return error
        items = CustomerModelProviderProfile.objects.filter(user=user).order_by("-is_active", "-updated_at", "-id")
        active = _active_profile(user)
        return ok_response(
            {
                "items": LlmProfileSerializer(items, many=True).data,
                "active_profile_id": active.id if active else None,
            }
        )

    @transaction.atomic
    def post(self, request):
        user, error = _auth_required(request)
        if error:
            return error
        serializer = LlmProfileCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _provider_config_invalid_response(serializer.errors)

        data = serializer.validated_data
        api_key_plain = (data.get("api_key") or "").strip()
        if api_key_plain:
            try:
                cipher = encrypt_api_key(api_key_plain)
            except ImproperlyConfigured as exc:
                return _encryption_config_error_response(exc)
            except ValueError as exc:
                return _provider_config_invalid_response({"api_key": str(exc)})
            masked = mask_api_key(api_key_plain)
        else:
            reuse_from = (
                CustomerModelProviderProfile.objects.filter(
                    user=user,
                    provider_type=data["provider_type"],
                    api_base_url=data["api_base_url"],
                )
                .exclude(api_key_ciphertext="")
                .order_by("-updated_at", "-id")
                .first()
            )
            if not reuse_from:
                reuse_from = (
                    CustomerModelProviderProfile.objects.filter(
                        user=user,
                        provider_type=data["provider_type"],
                    )
                    .exclude(api_key_ciphertext="")
                    .order_by("-is_active", "-updated_at", "-id")
                    .first()
                )
            if not reuse_from:
                return _provider_config_invalid_response(
                    {"api_key": "required_when_no_reusable_key_found"}
                )
            cipher = reuse_from.api_key_ciphertext
            masked = reuse_from.api_key_masked

        should_active = bool(data.get("is_active"))
        if not CustomerModelProviderProfile.objects.filter(user=user).exists():
            should_active = True

        try:
            profile = CustomerModelProviderProfile.objects.create(
                user=user,
                name=data["name"],
                provider_type=data["provider_type"],
                api_base_url=data["api_base_url"],
                model_name=data["model_name"],
                api_key_ciphertext=cipher,
                api_key_masked=masked,
                is_active=False,
                extra_json=data.get("extra_json") or {},
            )
        except IntegrityError:
            return _provider_config_invalid_response({"name": "already_exists"})

        if should_active:
            _activate_profile(user, profile)

        return ok_response(LlmProfileSerializer(profile).data, status_code=status.HTTP_201_CREATED)


class LlmProfileDetailView(APIView):
    @transaction.atomic
    def put(self, request, profile_id):
        user, error = _auth_required(request)
        if error:
            return error

        profile, access_error = _profile_with_permission(user, profile_id)
        if access_error:
            return access_error

        serializer = LlmProfileUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return _provider_config_invalid_response(serializer.errors)
        data = serializer.validated_data

        update_fields = []
        if "name" in data:
            profile.name = data["name"]
            update_fields.append("name")
        if "provider_type" in data:
            profile.provider_type = data["provider_type"]
            update_fields.append("provider_type")
        if "api_base_url" in data:
            profile.api_base_url = data["api_base_url"]
            update_fields.append("api_base_url")
        if "model_name" in data:
            profile.model_name = data["model_name"]
            update_fields.append("model_name")
        if "extra_json" in data:
            profile.extra_json = data["extra_json"] or {}
            update_fields.append("extra_json")

        if "api_key" in data and (data.get("api_key") or "").strip():
            try:
                profile.api_key_ciphertext = encrypt_api_key(data["api_key"])
            except ImproperlyConfigured as exc:
                return _encryption_config_error_response(exc)
            except ValueError as exc:
                return _provider_config_invalid_response({"api_key": str(exc)})
            profile.api_key_masked = mask_api_key(data["api_key"])
            update_fields.extend(["api_key_ciphertext", "api_key_masked"])

        is_active_value = data.get("is_active") if "is_active" in data else None
        if is_active_value is not None:
            profile.is_active = bool(is_active_value)
            update_fields.append("is_active")

        try:
            if update_fields:
                profile.save(update_fields=list(dict.fromkeys(update_fields + ["updated_at"])))
        except IntegrityError:
            return _provider_config_invalid_response({"name": "already_exists"})

        if is_active_value is True:
            _activate_profile(user, profile)
        elif is_active_value is False and profile.is_active is False:
            current_active = _active_profile(user)
            if not current_active:
                replacement = (
                    CustomerModelProviderProfile.objects.filter(user=user)
                    .exclude(id=profile.id)
                    .order_by("-updated_at", "-id")
                    .first()
                )
                if replacement:
                    _activate_profile(user, replacement)

        return ok_response(LlmProfileSerializer(_profile_for_user(user, profile_id)).data)

    @transaction.atomic
    def delete(self, request, profile_id):
        user, error = _auth_required(request)
        if error:
            return error

        profile, access_error = _profile_with_permission(user, profile_id)
        if access_error:
            return access_error

        was_active = profile.is_active
        deleted_id = profile.id
        profile.delete()

        if was_active:
            replacement = (
                CustomerModelProviderProfile.objects.filter(user=user).order_by("-updated_at", "-id").first()
            )
            if replacement:
                _activate_profile(user, replacement)

        return ok_response({"deleted_id": deleted_id})


class LlmProfileActivateView(APIView):
    @transaction.atomic
    def post(self, request, profile_id):
        user, error = _auth_required(request)
        if error:
            return error
        profile, access_error = _profile_with_permission(user, profile_id)
        if access_error:
            return access_error
        _activate_profile(user, profile)
        return ok_response(LlmProfileSerializer(profile).data)


class LlmProfileModelsView(APIView):
    def get(self, request, profile_id):
        user, error = _auth_required(request)
        if error:
            return error
        profile, access_error = _profile_with_permission(user, profile_id)
        if access_error:
            return access_error
        try:
            items = _fetch_models_by_profile(profile)
        except ImproperlyConfigured as exc:
            return _encryption_config_error_response(exc)
        except Exception as exc:
            return error_response(
                "PROVIDER_MODELS_UNAVAILABLE",
                "provider models unavailable",
                details={"detail": str(exc)},
                status_code=status.HTTP_502_BAD_GATEWAY,
            )
        return ok_response({"items": items, "count": len(items)})


class LlmProfileValidateView(APIView):
    def post(self, request, profile_id):
        user, error = _auth_required(request)
        if error:
            return error
        profile, access_error = _profile_with_permission(user, profile_id)
        if access_error:
            return access_error
        try:
            items = _fetch_models_by_profile(profile)
        except ImproperlyConfigured as exc:
            return _encryption_config_error_response(exc)
        except Exception as exc:
            return error_response(
                "PROVIDER_VALIDATE_FAILED",
                "provider validate failed",
                details={"detail": str(exc)},
                status_code=status.HTTP_502_BAD_GATEWAY,
            )
        return ok_response(
            {
                "reachable": True,
                "model_count": len(items),
                "sample_models": [item["id"] for item in items[:5]],
            }
        )


class ChatHistoryView(APIView):
    def get(self, request):
        user, error = _auth_required(request)
        if error:
            return error
        try:
            limit = int(request.query_params.get("limit", 200))
        except (TypeError, ValueError):
            limit = 200
        limit = max(1, min(500, limit))
        messages = list(
            CustomerChatMessage.objects.filter(user=user)
            .order_by("-created_at")
            .only("id", "role", "content", "run_id", "created_at")[:limit]
        )
        messages.reverse()
        return ok_response(
            {
                "items": CustomerChatMessageSerializer(messages, many=True).data,
                "count": len(messages),
            }
        )


class ChatHistoryClearView(APIView):
    def post(self, request):
        user, error = _auth_required(request)
        if error:
            return error
        deleted_count, _ = CustomerChatMessage.objects.filter(user=user).delete()
        memory_cleared = False
        try:
            memory = CustomerConversationMemory.objects.filter(user=user).first()
            if memory:
                memory.memory_json = {}
                memory.save(update_fields=["memory_json", "updated_at"])
                memory_cleared = True
        except Exception:
            memory_cleared = False
        return ok_response({"deleted_count": deleted_count, "memory_cleared": memory_cleared})
