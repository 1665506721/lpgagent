from django.apps import AppConfig
from django.db.models.signals import post_migrate


class CustomerPortalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "customer_portal"

    def ready(self):
        from .auth_helpers import ensure_test_account

        def _init_test_account(sender, **kwargs):
            if sender.name != self.name:
                return
            ensure_test_account()

        post_migrate.connect(
            _init_test_account,
            sender=self,
            dispatch_uid="customer_portal_init_test_account",
        )
