from django.core.management.base import BaseCommand

from knowledge_base import BIZ_DOMAIN, SAFETY_DOMAIN
from knowledge_base.vector_store import rebuild_vector_store


class Command(BaseCommand):
    help = "Rebuild knowledge base indexes for safety/biz domains."

    def add_arguments(self, parser):
        parser.add_argument(
            "--domain",
            choices=[SAFETY_DOMAIN, BIZ_DOMAIN, "all"],
            default="all",
            help="Domain to rebuild: safety, biz, or all.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Drop existing collections before rebuilding.",
        )

    def handle(self, *args, **options):
        # 中文注释：按 domain 重建索引并输出统计信息
        domain = options["domain"]
        force = options["force"]
        targets = [SAFETY_DOMAIN, BIZ_DOMAIN] if domain == "all" else [domain]

        for target in targets:
            result = rebuild_vector_store(target, force=force)
            self.stdout.write(
                f"[{target}] docs={result['documents']} chunks={result['chunks']}"
            )
            self.stdout.write(f"[{target}] collection={result['collection']}")
            self.stdout.write(f"[{target}] persist_path={result['persist_path']}")
            if result.get("provider"):
                self.stdout.write(
                    f"[{target}] embed_provider={result.get('provider')} actual={result.get('actual_provider')} model={result.get('model')} device={result.get('device')}"
                )
