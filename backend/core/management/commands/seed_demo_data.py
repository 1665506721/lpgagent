from django.core.management.base import BaseCommand

from core.models import AgentEvent, AgentRun, Order, Ticket, UserProfile


class Command(BaseCommand):
    help = "Seed demo data for manual verification."

    def handle(self, *args, **options):
        user, created = UserProfile.objects.get_or_create(
            id=1,
            defaults={"name": "Demo User"},
        )
        if created:
            self.stdout.write("Created UserProfile id=1")
        else:
            self.stdout.write("Reusing UserProfile id=1")

        order_created = Order.objects.create(
            user=user,
            product_type="15kg",
            quantity=1,
            status=Order.STATUS_CREATED,
            address="Demo Street 1",
        )
        order_delivering = Order.objects.create(
            user=user,
            product_type="5kg",
            quantity=2,
            status=Order.STATUS_DELIVERING,
            address="Demo Street 2",
        )
        self.stdout.write(f"Created Order id={order_created.id} status={order_created.status}")
        self.stdout.write(f"Created Order id={order_delivering.id} status={order_delivering.status}")

        ticket = Ticket.objects.create(
            user=user,
            order=order_created,
            category=Ticket.CATEGORY_DELIVERY_DELAY,
            description="Delivery is late",
            status=Ticket.STATUS_OPEN,
        )
        self.stdout.write(f"Created Ticket id={ticket.id} category={ticket.category}")

        run = AgentRun.objects.create(
            user=user,
            model_provider=AgentRun.PROVIDER_OPENAI,
        )
        event_init = AgentEvent.objects.create(
            run=run,
            step_index=1,
            state=AgentEvent.STATE_INIT,
            input_json={"message": "demo init"},
            policy_result={"allow": True, "reasons": []},
        )
        event_tool = AgentEvent.objects.create(
            run=run,
            step_index=2,
            state=AgentEvent.STATE_TOOL_EXEC,
            tool_name="create_order",
            tool_input={"user_id": user.id},
            tool_output={"order_id": order_created.id},
            policy_result={"allow": True, "reasons": []},
        )
        self.stdout.write(
            f"Created AgentRun id={run.id} with events {event_init.id}, {event_tool.id}"
        )
