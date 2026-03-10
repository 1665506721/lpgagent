from django.core.management.base import BaseCommand, CommandError

from knowledge_base.ingest_service import reindex_document


class Command(BaseCommand):
    help = "Reindex a document by doc_id or local file path."

    def add_arguments(self, parser):
        parser.add_argument("--doc-id", dest="doc_id", help="Existing document id.")
        parser.add_argument("--file", dest="file_path", help="Local file path to reindex.")
        parser.add_argument("--domain", choices=["biz", "safety"], help="Required when using --file.")
        parser.add_argument("--source", help="Optional source override when using --file.")
        parser.add_argument("--versioning-strategy", default="keep_history", choices=["replace", "keep_history"])
        parser.add_argument("--chunk-size", type=int, default=800)
        parser.add_argument("--overlap", type=int, default=120)

    def handle(self, *args, **options):
        if not options.get("doc_id") and not options.get("file_path"):
            raise CommandError("--doc-id or --file is required")
        result = reindex_document(
            doc_id=options.get("doc_id"),
            file_path=options.get("file_path"),
            domain=options.get("domain"),
            source=options.get("source"),
            versioning_strategy=options["versioning_strategy"],
            chunk_size=options["chunk_size"],
            overlap=options["overlap"],
        )
        self.stdout.write(
            f"doc_id={result.doc_id} version={result.version} file={result.file_name} chunks={result.chunks}"
        )
