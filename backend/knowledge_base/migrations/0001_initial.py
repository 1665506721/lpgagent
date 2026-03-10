from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="KnowledgeDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("doc_id", models.CharField(db_index=True, max_length=64)),
                ("domain", models.CharField(db_index=True, max_length=32)),
                ("source", models.CharField(db_index=True, max_length=512)),
                ("file_name", models.CharField(max_length=255)),
                ("doc_type", models.CharField(db_index=True, max_length=32)),
                ("title", models.CharField(blank=True, default="", max_length=255)),
                ("version", models.IntegerField(default=1)),
                ("checksum", models.CharField(blank=True, default="", max_length=64)),
                ("storage_path", models.CharField(blank=True, default="", max_length=1024)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("ACTIVE", "ACTIVE"),
                            ("SUPERSEDED", "SUPERSEDED"),
                            ("DELETED", "DELETED"),
                            ("FAILED", "FAILED"),
                        ],
                        default="ACTIVE",
                        max_length=32,
                    ),
                ),
                ("is_current", models.BooleanField(db_index=True, default=True)),
                ("chunk_count", models.IntegerField(default=0)),
                ("extra_metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["domain", "source", "is_current"], name="kb_doc_dom_src_cur_idx"),
                    models.Index(fields=["domain", "doc_id", "is_current"], name="kb_doc_dom_doc_cur_idx"),
                ],
                "unique_together": {("doc_id", "version")},
            },
        ),
    ]
