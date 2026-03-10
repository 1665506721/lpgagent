from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from knowledge_base.ingest_service import batch_ingest_files


class Command(BaseCommand):
    help = "Ingest one file or all supported files in a directory into the knowledge base."

    def add_arguments(self, parser):
        parser.add_argument("--file", dest="file_path", help="Single file path to ingest.")
        parser.add_argument("--dir", dest="dir_path", help="Directory to scan for supported files.")
        parser.add_argument("--domain", required=True, choices=["biz", "safety"], help="Knowledge domain.")
        parser.add_argument("--versioning-strategy", default="replace", choices=["replace", "keep_history"])
        parser.add_argument("--chunk-size", type=int, default=800)
        parser.add_argument("--overlap", type=int, default=120)

    def handle(self, *args, **options):
        file_path = options.get("file_path")
        dir_path = options.get("dir_path")
        if not file_path and not dir_path:
            raise CommandError("--file or --dir is required")
        files = []
        if file_path:
            files.append(file_path)
        if dir_path:
            root = Path(dir_path)
            if not root.exists():
                raise CommandError(f"Directory not found: {dir_path}")
            for pattern in ["*.pdf", "*.docx", "*.md", "*.txt", "*.xlsx", "*.png", "*.jpg", "*.jpeg"]:
                files.extend(str(path) for path in root.rglob(pattern))
        results = batch_ingest_files(
            files,
            domain=options["domain"],
            versioning_strategy=options["versioning_strategy"],
            chunk_size=options["chunk_size"],
            overlap=options["overlap"],
        )
        for item in results:
            self.stdout.write(
                f"doc_id={item.doc_id} version={item.version} file={item.file_name} chunks={item.chunks} skipped={item.skipped}"
            )
