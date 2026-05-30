import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import current_app

from app.extensions import db
from app.models import Agent, AuditLog, Memory, Session, SessionMessage, Workspace
from app.services.memory_service import serialize_memory


class BackupService:
    def backup_dir(self):
        path = Path(current_app.root_path).parent / "backups"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create_backup(self):
        stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        db_uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
        target = self.backup_dir() / f"human_brain_full_{stamp}.zip"
        manifest = {
            "app": "Human-Brain",
            "created_at": stamp,
            "database_uri_type": "sqlite" if db_uri.startswith("sqlite") else "postgresql",
            "contains_secrets": False,
            "restore_notes": "Restore through the Backups page or python manage.py restore for SQLite development.",
        }
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            self._zip_dir(archive, Path(current_app.config["FAISS_INDEX_DIR"]), "faiss_indexes")
            self._zip_dir(archive, Path(current_app.config["SNAPSHOT_DIR"]).parent, "uploads")
            if db_uri.startswith("sqlite:///") and db_uri != "sqlite:///:memory:":
                source = Path(db_uri.removeprefix("sqlite:///"))
                if source.exists():
                    archive.write(source, "database/human_brain.sqlite3")
            elif db_uri == "sqlite:///:memory:":
                archive.writestr("database/README.txt", "In-memory test database cannot be backed up as a file.")
            else:
                archive.writestr("database/README.txt", "PostgreSQL data is not embedded. Use pg_dump for production DB backups.")
        return {"type": "zip", "path": str(target), "created_at": stamp}

    def _zip_dir(self, archive, source_dir, archive_prefix):
        if not source_dir.exists():
            return
        for path in source_dir.rglob("*"):
            if path.is_file():
                archive.write(path, f"{archive_prefix}/{path.relative_to(source_dir)}")

    def restore_backup(self, zip_file):
        db_uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with zipfile.ZipFile(zip_file) as archive:
                self._safe_extract(archive, tmp_path)
            faiss_source = tmp_path / "faiss_indexes"
            uploads_source = tmp_path / "uploads"
            if faiss_source.exists():
                target = Path(current_app.config["FAISS_INDEX_DIR"])
                target.mkdir(parents=True, exist_ok=True)
                shutil.copytree(faiss_source, target, dirs_exist_ok=True)
            if uploads_source.exists():
                target = Path(current_app.config["SNAPSHOT_DIR"]).parent
                target.mkdir(parents=True, exist_ok=True)
                shutil.copytree(uploads_source, target, dirs_exist_ok=True)
            sqlite_backup = tmp_path / "database" / "human_brain.sqlite3"
            if sqlite_backup.exists() and db_uri.startswith("sqlite:///") and db_uri != "sqlite:///:memory:":
                shutil.copy2(sqlite_backup, Path(db_uri.removeprefix("sqlite:///")))
                return {"restored": True, "database": "sqlite", "assets": True}
            return {"restored": True, "database": "not_restored", "assets": True}

    def _safe_extract(self, archive, target_dir):
        for member in archive.infolist():
            destination = target_dir / member.filename
            if not destination.resolve().is_relative_to(target_dir.resolve()):
                raise ValueError("Unsafe zip path")
        archive.extractall(target_dir)

    def create_legacy_file_backup(self):
        stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        db_uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
        if db_uri == "sqlite:///:memory:":
            target = self.backup_dir() / f"human_brain_memory_manifest_{stamp}.json"
            target.write_text(json.dumps({"database": "sqlite_memory", "instruction": "In-memory test databases cannot be file-backed up."}, indent=2), encoding="utf-8")
            return {"type": "sqlite_memory_manifest", "path": str(target), "created_at": stamp}
        if db_uri.startswith("sqlite:///"):
            source = Path(db_uri.removeprefix("sqlite:///"))
            target = self.backup_dir() / f"human_brain_{stamp}.sqlite3"
            shutil.copy2(source, target)
            return {"type": "sqlite", "path": str(target), "created_at": stamp}
        target = self.backup_dir() / f"human_brain_manifest_{stamp}.json"
        target.write_text(json.dumps({"database": "postgresql", "instruction": "Use pg_dump for production PostgreSQL backups."}, indent=2), encoding="utf-8")
        return {"type": "postgresql_manifest", "path": str(target), "created_at": stamp}

    def list_backups(self):
        return sorted(self.backup_dir().glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)

    def backup_items(self):
        items = []
        for path in self.list_backups():
            stat = path.stat()
            items.append(
                {
                    "name": path.name,
                    "size": stat.st_size,
                    "size_label": self._format_size(stat.st_size),
                    "modified": stat.st_mtime,
                    "kind": "Full zip" if path.suffix == ".zip" else path.suffix.replace(".", "").upper() or "File",
                }
            )
        return items

    def _format_size(self, size):
        units = ["B", "KB", "MB", "GB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024

    def delete_backup(self, filename):
        path = self.backup_dir() / Path(filename).name
        if path.exists() and path.is_file():
            path.unlink()
            return path
        return None

    def export_agent_brain(self, agent_id):
        agent = db.session.get(Agent, agent_id)
        memories = Memory.query.filter_by(agent_id=agent_id).filter(Memory.deleted_at.is_(None)).all()
        sessions = Session.query.filter_by(agent_id=agent_id).all()
        payload = {
            "exported_at": datetime.utcnow().isoformat(),
            "agent": {"id": agent.id, "uuid": agent.uuid, "name": agent.name, "description": agent.description},
            "workspaces": [{"id": w.id, "uuid": w.uuid, "name": w.name} for w in Workspace.query.all()],
            "memories": [serialize_memory(memory) for memory in memories],
            "sessions": [
                {
                    "id": session.id,
                    "uuid": session.uuid,
                    "title": session.title,
                    "messages": [
                        {"role": msg.role, "content": msg.content, "created_at": msg.created_at.isoformat()}
                        for msg in SessionMessage.query.filter_by(session_id=session.id).all()
                    ],
                }
                for session in sessions
            ],
            "audit_count": AuditLog.query.filter_by(actor_type="agent", actor_id=str(agent_id)).count(),
        }
        target = self.backup_dir() / f"agent_{agent_id}_brain_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.json"
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return target
