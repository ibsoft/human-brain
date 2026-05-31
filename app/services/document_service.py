from datetime import datetime
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import MemoryAsset
from app.services.asset_vector_service import AssetVectorService
from app.services.memory_service import MemoryService, asset_url
from app.utils.hash import sha256_text


TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".json", ".csv", ".log", ".yaml", ".yml", ".py", ".js", ".html", ".css", ".xml"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}


class DocumentIngestionService:
    def ingest_uploads(self, uploads, base_payload, actor_id=None, mode="all", chunk_size=4000):
        created = []
        for upload in uploads:
            if not upload or not upload.filename:
                continue
            stored_path = self._save(upload)
            payloads = self._payloads_for_file(stored_path, upload.mimetype, base_payload, mode, chunk_size)
            for payload in payloads:
                memory, _ = MemoryService().add_memory(payload, actor_type="user", actor_id=actor_id)
                asset = self._create_asset(memory, stored_path, upload.filename, upload.mimetype, payload.get("_asset_type", "document"), payload.get("_asset_text"))
                self._attach_asset_url(memory, asset)
                created.append(memory)
        return created

    def _save(self, upload):
        upload_dir = Path(current_app.config["MEMORY_UPLOAD_DIR"])
        upload_dir.mkdir(parents=True, exist_ok=True)
        filename = secure_filename(upload.filename) or "upload.bin"
        stamped = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
        path = upload_dir / stamped
        upload.save(path)
        return path

    def _payloads_for_file(self, path, mimetype, base_payload, mode, chunk_size):
        ext = path.suffix.lower()
        tags = list(base_payload.get("tags") or [])
        tags.extend(["upload", ext.lstrip(".") or "file"])
        common = {
            **base_payload,
            "tags": sorted(set(tags)),
            "source": "upload",
            "storage_reason": f"Stored from uploaded file {path.name}.",
        }
        if ext in IMAGE_EXTENSIONS or str(mimetype).startswith("image/"):
            vector, vector_hash, metadata = AssetVectorService().image_vector(path)
            content = (
                f"Uploaded image: {path.name}\n"
                "Asset URL: pending\n"
                f"MIME type: {mimetype or 'unknown'}\n"
                f"Image vector: {metadata.get('vector_kind')} {vector_hash}\n"
                f"Visual profile: {metadata.get('width')}x{metadata.get('height')}, dominant color {metadata.get('dominant_color')}.\n"
                "Image bytes are available through the tokenized asset URL. Visual fingerprint metadata is stored for correlation."
            )
            image_tags = sorted(set(common["tags"] + ["image", "visual", metadata.get("dominant_color", "")]))
            return [
                {
                    **common,
                    "title": common.get("title") or path.name,
                    "content": content,
                    "summary": f"Uploaded image with {metadata.get('vector_kind')} vector.",
                    "memory_type": "vision",
                    "tags": [tag for tag in image_tags if tag],
                    "_asset_type": "image",
                    "_asset_vector": vector,
                    "_asset_hash": vector_hash,
                    "_asset_metadata": metadata,
                }
            ]

        text = self._extract_text(path, mimetype)
        vector, vector_hash, metadata = AssetVectorService().document_vector(text, path)
        common["_asset_type"] = "document"
        common["_asset_text"] = text
        common["_asset_vector"] = vector
        common["_asset_hash"] = vector_hash
        common["_asset_metadata"] = metadata
        if mode == "chunks":
            chunks = self._chunk_text(text, max(500, int(chunk_size or 4000)))
            return [
                {
                    **common,
                    "title": f"{common.get('title') or path.name} - chunk {index + 1}",
                    "content": chunk,
                    "summary": f"Chunk {index + 1} from uploaded file {path.name}.",
                }
                for index, chunk in enumerate(chunks)
            ]
        return [{**common, "title": common.get("title") or path.name, "content": text}]

    def _create_asset(self, memory, path, original_filename, mimetype, asset_type, asset_text=None):
        metadata = {}
        vector = None
        vector_hash = None
        if asset_type == "image":
            vector, vector_hash, metadata = AssetVectorService().image_vector(path)
        else:
            vector, vector_hash, metadata = AssetVectorService().document_vector(asset_text or memory.content, path)
        db.session.add(
            asset := MemoryAsset(
                memory_id=memory.id,
                workspace_id=memory.workspace_id,
                asset_type=asset_type,
                original_filename=original_filename,
                stored_path=str(path),
                content_type=mimetype,
                vector_hash=vector_hash,
                vector_dim=len(vector) if vector else None,
                vector=vector,
                asset_metadata=metadata,
            )
        )
        db.session.commit()
        try:
            from app.services.correlation_service import CorrelationService

            CorrelationService().correlate_memory(memory)
        except Exception:
            current_app.logger.exception("Could not correlate uploaded asset memory")
        return asset

    def _attach_asset_url(self, memory, asset):
        url = asset_url(asset, external=True)
        if "Asset URL: pending" in memory.content:
            memory.content = memory.content.replace("Asset URL: pending", f"Asset URL: {url}")
        elif "Asset URL:" not in memory.content:
            memory.content = f"{memory.content.rstrip()}\n\nAsset URL: {url}"
        memory.content_hash = sha256_text(memory.content.strip())
        db.session.commit()
        try:
            service = MemoryService()
            service.faiss.upsert_memory(memory, service.embedding_service)
        except Exception:
            current_app.logger.exception("Could not refresh uploaded asset memory vector after asset URL attach")

    def _extract_text(self, path, mimetype):
        ext = path.suffix.lower()
        if ext in TEXT_EXTENSIONS or str(mimetype).startswith("text/"):
            return path.read_text(encoding="utf-8", errors="replace")
        if ext == ".pdf":
            return self._extract_pdf(path)
        if ext == ".docx":
            return self._extract_docx(path)
        if ext in {".xlsx", ".xlsm"}:
            return self._extract_xlsx(path)
        if ext == ".csv":
            return path.read_text(encoding="utf-8", errors="replace")
        return (
            f"Uploaded document: {path.name}\n"
            "Asset URL: pending\n"
            f"MIME type: {mimetype or 'unknown'}\n"
            "This file type is stored as an attachment. Install a parser and re-ingest if full text extraction is required."
        )

    def _extract_pdf(self, path):
        try:
            from pypdf import PdfReader
        except Exception:
            try:
                from PyPDF2 import PdfReader
            except Exception:
                return self._unsupported_text(path, "PDF text extraction requires pypdf or PyPDF2.")
        try:
            reader = PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n\n".join(page.strip() for page in pages if page.strip())
            return text or self._unsupported_text(path, "No extractable text found in PDF.")
        except Exception as exc:
            return self._unsupported_text(path, f"PDF extraction failed: {exc}")

    def _extract_docx(self, path):
        try:
            from docx import Document
        except Exception:
            return self._unsupported_text(path, "DOCX extraction requires python-docx.")
        try:
            document = Document(str(path))
            paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
            for table in document.tables:
                for row in table.rows:
                    paragraphs.append(" | ".join(cell.text.strip() for cell in row.cells))
            return "\n".join(paragraphs) or self._unsupported_text(path, "No extractable text found in DOCX.")
        except Exception as exc:
            return self._unsupported_text(path, f"DOCX extraction failed: {exc}")

    def _extract_xlsx(self, path):
        try:
            from openpyxl import load_workbook
        except Exception:
            return self._unsupported_text(path, "XLSX extraction requires openpyxl.")
        try:
            workbook = load_workbook(str(path), read_only=True, data_only=True)
            lines = []
            for sheet in workbook.worksheets:
                lines.append(f"Sheet: {sheet.title}")
                for row in sheet.iter_rows(values_only=True):
                    values = [str(value) for value in row if value is not None]
                    if values:
                        lines.append(" | ".join(values))
            return "\n".join(lines) or self._unsupported_text(path, "No extractable values found in spreadsheet.")
        except Exception as exc:
            return self._unsupported_text(path, f"Spreadsheet extraction failed: {exc}")

    def _unsupported_text(self, path, reason):
        return (
            f"Uploaded document: {path.name}\n"
            "Asset URL: pending\n"
            f"Extraction note: {reason}\n"
            "The original file is linked to this memory through the tokenized asset URL."
        )

    def _chunk_text(self, text, chunk_size):
        text = text.strip()
        if not text:
            return ["Empty uploaded document."]
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            if end < len(text):
                boundary = text.rfind("\n", start, end)
                if boundary > start + chunk_size // 2:
                    end = boundary
            chunks.append(text[start:end].strip())
            start = end
        return [chunk for chunk in chunks if chunk]
