from django.urls import path

from knowledge_base import views


urlpatterns = [
    path("ingest", views.IngestView.as_view(), name="kb-ingest"),
    path("ingest/batch", views.BatchIngestView.as_view(), name="kb-ingest-batch"),
    path("reindex", views.ReindexView.as_view(), name="kb-reindex"),
    path("documents", views.DocumentListView.as_view(), name="kb-documents"),
    path("documents/<str:doc_id>", views.DocumentDeleteView.as_view(), name="kb-document-delete"),
]
