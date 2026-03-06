from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("customer_portal", "0003_customerfeedback"),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerChatPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "tone_style",
                    models.CharField(
                        choices=[("neutral", "neutral"), ("warm", "warm"), ("direct", "direct")],
                        default="neutral",
                        max_length=16,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
                ),
            ],
        ),
    ]
