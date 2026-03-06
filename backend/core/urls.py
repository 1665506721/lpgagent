from django.urls import path

from core import views


urlpatterns = [
    path("chat", views.ChatView.as_view(), name="chat"),
    path("health", views.HealthView.as_view(), name="health"),
    path("ollama/models", views.OllamaModelsView.as_view(), name="ollama-models"),
    path("ollama/warmup", views.OllamaWarmupView.as_view(), name="ollama-warmup"),
    path("runs", views.RunsListView.as_view(), name="runs-list"),
    path("runs/<uuid:run_id>", views.RunDetailView.as_view(), name="run-detail"),
    path(
        "external/orders/<int:order_id>",
        views.ExternalOrderDetailView.as_view(),
        name="external-order-detail",
    ),
    path(
        "external/orders",
        views.ExternalOrderListView.as_view(),
        name="external-order-list",
    ),
    path(
        "external/orders/seed",
        views.ExternalOrderSeedView.as_view(),
        name="external-order-seed",
    ),
    path("tools/create_order", views.CreateOrderView.as_view(), name="create-order"),
    path("tools/query_order", views.QueryOrderView.as_view(), name="query-order"),
    path(
        "tools/modify_order_address",
        views.ModifyOrderAddressView.as_view(),
        name="modify-order-address",
    ),
    path("tools/create_ticket", views.CreateTicketView.as_view(), name="create-ticket"),
    path("tools/query_ticket", views.QueryTicketView.as_view(), name="query-ticket"),
    path(
        "tools/create_maintenance_request",
        views.CreateMaintenanceRequestView.as_view(),
        name="create-maintenance-request",
    ),
    path("tools/safety_search", views.SafetySearchView.as_view(), name="safety-search"),
    path("tools/kb_search", views.KnowledgeBaseSearchView.as_view(), name="kb-search"),
]
