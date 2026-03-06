from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("phone", models.CharField(max_length=32, unique=True)),
                ("display_name", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="CustomerAddress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("contact_name", models.CharField(max_length=64)),
                ("contact_phone", models.CharField(max_length=32)),
                ("address_full", models.TextField()),
                ("door_note", models.TextField(blank=True)),
                ("is_default", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="Order",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("order_no", models.CharField(max_length=32, unique=True)),
                ("service_type", models.CharField(choices=[("LPG_CYLINDER_DELIVERY", "LPG_CYLINDER_DELIVERY"), ("CYLINDER_EXCHANGE", "CYLINDER_EXCHANGE"), ("INSTALLATION", "INSTALLATION"), ("SAFETY_CHECK", "SAFETY_CHECK"), ("REPAIR", "REPAIR"), ("ACCESSORIES", "ACCESSORIES")], max_length=64)),
                ("status", models.CharField(choices=[("PENDING_PAYMENT", "PENDING_PAYMENT"), ("PAID", "PAID"), ("SCHEDULED", "SCHEDULED"), ("IN_SERVICE", "IN_SERVICE"), ("COMPLETED", "COMPLETED"), ("CANCELED", "CANCELED"), ("EXPIRED", "EXPIRED")], max_length=32)),
                ("eta_start", models.DateTimeField()),
                ("eta_end", models.DateTimeField()),
                ("cancel_deadline", models.DateTimeField()),
                ("address_edit_deadline", models.DateTimeField()),
                ("is_urgent", models.BooleanField(default=False)),
                ("notes", models.TextField(blank=True)),
                ("amount_subtotal", models.DecimalField(decimal_places=2, max_digits=10)),
                ("amount_urgent_fee", models.DecimalField(decimal_places=2, max_digits=10)),
                ("amount_total", models.DecimalField(decimal_places=2, max_digits=10)),
                ("currency", models.CharField(default="CNY", max_length=8)),
                ("address_snapshot", models.JSONField()),
                ("contact_snapshot", models.JSONField()),
                ("service_payload", models.JSONField()),
                ("expires_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="SmsVerification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("phone", models.CharField(max_length=32)),
                ("code", models.CharField(max_length=8)),
                ("purpose", models.CharField(choices=[("REGISTER", "REGISTER"), ("RESET", "RESET")], max_length=16)),
                ("expires_at", models.DateTimeField()),
                ("is_used", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="CustomerAuthToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="PaymentTransaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("SUCCESS", "SUCCESS"), ("FAILED", "FAILED"), ("MOCK", "MOCK")], max_length=16)),
                ("method", models.CharField(default="MOCK", max_length=16)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="customer_portal.order")),
            ],
        ),
        migrations.CreateModel(
            name="OrderEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(max_length=64)),
                ("payload", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="customer_portal.order")),
            ],
        ),
    ]
