from django.urls import path

from . import views


urlpatterns = [
    path("auth/register", views.RegisterView.as_view(), name="portal-register"),
    path("auth/login", views.LoginView.as_view(), name="portal-login"),
    path("auth/sms", views.SmsRequestView.as_view(), name="portal-sms"),
    path("me", views.MeView.as_view(), name="portal-me"),
    path("me/password", views.MePasswordView.as_view(), name="portal-me-password"),
    path("addresses", views.AddressListCreateView.as_view(), name="portal-addresses"),
    path("addresses/<int:address_id>", views.AddressDetailView.as_view(), name="portal-address-detail"),
    path(
        "addresses/<int:address_id>/default",
        views.AddressDefaultView.as_view(),
        name="portal-address-default",
    ),
    path("cart/items", views.CartItemListCreateView.as_view(), name="portal-cart-items"),
    path("cart/items/<str:sku>", views.CartItemDetailView.as_view(), name="portal-cart-item-detail"),
    path("cart/clear", views.CartClearView.as_view(), name="portal-cart-clear"),
    path("cart/checkout", views.CartCheckoutView.as_view(), name="portal-cart-checkout"),
    path("services", views.ServiceListView.as_view(), name="portal-services"),
    path("services/<str:code>/form", views.ServiceFormView.as_view(), name="portal-service-form"),
    path("orders", views.OrderListCreateView.as_view(), name="portal-orders"),
    path("orders/<int:order_id>", views.OrderDetailView.as_view(), name="portal-order-detail"),
    path("orders/<int:order_id>/pay", views.OrderPayView.as_view(), name="portal-order-pay"),
    path("orders/<int:order_id>/cancel", views.OrderCancelView.as_view(), name="portal-order-cancel"),
    path(
        "orders/<int:order_id>/modify-address",
        views.OrderModifyAddressView.as_view(),
        name="portal-order-modify-address",
    ),
    path("feedbacks", views.FeedbackListCreateView.as_view(), name="portal-feedbacks"),
    path("notifications", views.NotificationListView.as_view(), name="portal-notifications"),
    path(
        "notifications/<int:notification_id>/read",
        views.NotificationReadView.as_view(),
        name="portal-notification-read",
    ),
    path("notifications/read-all", views.NotificationReadAllView.as_view(), name="portal-notifications-read-all"),
    path("llm-profiles", views.LlmProfileListCreateView.as_view(), name="portal-llm-profiles"),
    path("llm-profiles/<int:profile_id>", views.LlmProfileDetailView.as_view(), name="portal-llm-profile-detail"),
    path(
        "llm-profiles/<int:profile_id>/activate",
        views.LlmProfileActivateView.as_view(),
        name="portal-llm-profile-activate",
    ),
    path(
        "llm-profiles/<int:profile_id>/models",
        views.LlmProfileModelsView.as_view(),
        name="portal-llm-profile-models",
    ),
    path(
        "llm-profiles/<int:profile_id>/validate",
        views.LlmProfileValidateView.as_view(),
        name="portal-llm-profile-validate",
    ),
    path("chat/history", views.ChatHistoryView.as_view(), name="portal-chat-history"),
    path("chat/history/clear", views.ChatHistoryClearView.as_view(), name="portal-chat-history-clear"),
]
