from django.db import models


class KnowledgeDocument(models.Model):
    STATUS_ACTIVE = "ACTIVE"
    STATUS_SUPERSEDED = "SUPERSEDED"
    STATUS_DELETED = "DELETED"
    STATUS_FAILED = "FAILED"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, STATUS_ACTIVE),
        (STATUS_SUPERSEDED, STATUS_SUPERSEDED),
        (STATUS_DELETED, STATUS_DELETED),
        (STATUS_FAILED, STATUS_FAILED),
    ]

    doc_id = models.CharField(max_length=64, db_index=True)
    domain = models.CharField(max_length=32, db_index=True)
    source = models.CharField(max_length=512, db_index=True)
    file_name = models.CharField(max_length=255)
    doc_type = models.CharField(max_length=32, db_index=True)
    title = models.CharField(max_length=255, blank=True, default="")
    version = models.IntegerField(default=1)
    checksum = models.CharField(max_length=64, blank=True, default="")
    storage_path = models.CharField(max_length=1024, blank=True, default="")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    is_current = models.BooleanField(default=True, db_index=True)
    chunk_count = models.IntegerField(default=0)
    extra_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("doc_id", "version")]
        indexes = [
            models.Index(fields=["domain", "source", "is_current"], name="kb_doc_dom_src_cur_idx"),
            models.Index(fields=["domain", "doc_id", "is_current"], name="kb_doc_dom_doc_cur_idx"),
        ]

    def __str__(self):
        return f"{self.domain}:{self.doc_id}:v{self.version}"
