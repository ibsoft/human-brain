import json
from io import BytesIO
from pathlib import Path

from app.extensions import db
from app.models import AuditLog, Memory, MemoryAsset, SessionMessage, User, Workspace
from app.services.agent_log_service import AgentLogService
from app.services.backup_service import BackupService
from app.services.correlation_service import CorrelationService
from app.services.reranker_service import RerankerService
from app.services.settings_service import SettingsService
from app.services.vision_service import VisionRuntime, VisionService
from app.workers.tasks import consolidate_session_task


def test_auth_login(client):
    res = client.post("/login", data={"email": "admin@example.com", "password": "password"}, follow_redirects=True)
    assert res.status_code == 200


def test_first_run_setup_creates_admin(client, app):
    with app.app_context():
        db.session.expunge_all()
        User.query.delete()
        db.session.commit()
        db.session.expunge_all()
    res = client.get("/login")
    assert res.status_code == 302
    assert "/setup" in res.headers["Location"]
    res = client.post(
        "/setup",
        data={
            "name": "First Admin",
            "email": "first@example.com",
            "password": "long-secure-password",
            "confirm_password": "long-secure-password",
        },
        follow_redirects=False,
    )
    assert res.status_code == 302
    with app.app_context():
        admin = User.query.filter_by(email="first@example.com").first()
        assert admin is not None
        assert admin.role == "admin"


def test_api_key_required(client):
    res = client.post("/api/v1/memory/add", json={})
    assert res.status_code == 401


def test_web_admin_create_workspace_agent_and_key(client):
    client.post("/login", data={"email": "admin@example.com", "password": "password"})
    workspace = client.post("/workspaces", data={"name": "UI Workspace", "description": "Created from UI"}, follow_redirects=True)
    assert workspace.status_code == 200
    agent = client.post("/agents", data={"name": "UI Agent", "description": "Created from UI", "workspace_id": "1"}, follow_redirects=True)
    assert agent.status_code == 200
    key = client.post("/api-keys", data={"agent_id": "1", "name": "UI key"}, follow_redirects=True)
    assert key.status_code == 200


def test_image_upload_memory_uses_tokenized_asset_url(client, app):
    client.post("/login", data={"email": "admin@example.com", "password": "password"})
    res = client.post(
        "/memories",
        data={
            "memory_input_mode": "image",
            "agent_id": str(app.config["TEST_AGENT_ID"]),
            "workspace_id": str(app.config["TEST_WORKSPACE_ID"]),
            "title": "Remote image asset",
            "memory_type": "vision",
            "uploads": (BytesIO(b"not-a-real-image-but-stored"), "mine.jpg"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert res.status_code == 200
    with app.app_context():
        memory = Memory.query.filter_by(title="Remote image asset").one()
        asset = MemoryAsset.query.filter_by(memory_id=memory.id).one()
        assert "Stored path:" not in memory.content
        assert str(app.config["MEMORY_UPLOAD_DIR"]) not in memory.content
        assert f"/memory-assets/{asset.public_token}" in memory.content
        asset_url = f"/memory-assets/{asset.public_token}"
        stored_path = asset.stored_path
    public_client = app.test_client()
    asset_res = public_client.get(asset_url)
    assert asset_res.status_code == 200
    assert asset_res.data == b"not-a-real-image-but-stored"
    Path(stored_path).unlink(missing_ok=True)


def test_duplicate_image_upload_reuses_existing_memory(client, app, api_headers):
    first = client.post(
        "/api/v1/memory/upload",
        data={
            "workspace_id": str(app.config["TEST_WORKSPACE_ID"]),
            "title": "Duplicate image asset",
            "memory_type": "vision",
            "confirmed": "true",
            "uploads": (BytesIO(b"same-image-bytes"), "logo.jpg"),
        },
        headers=api_headers,
        content_type="multipart/form-data",
    )
    assert first.status_code == 201
    first_memory = first.get_json()["memories"][0]

    second = client.post(
        "/api/v1/memory/upload",
        data={
            "workspace_id": str(app.config["TEST_WORKSPACE_ID"]),
            "title": "Duplicate image asset",
            "memory_type": "vision",
            "confirmed": "true",
            "uploads": (BytesIO(b"same-image-bytes"), "logo.jpg"),
        },
        headers=api_headers,
        content_type="multipart/form-data",
    )
    assert second.status_code == 201
    assert second.get_json()["memories"][0]["id"] == first_memory["id"]

    with app.app_context():
        memories = Memory.query.filter_by(title="Duplicate image asset").all()
        assets = MemoryAsset.query.filter_by(memory_id=first_memory["id"]).all()
        assert len(memories) == 1
        assert len(assets) == 1
        assert memories[0].trust_score == 0.55
        Path(assets[0].stored_path).unlink(missing_ok=True)


def test_agent_upload_document_as_full_memory(client, app, api_headers):
    res = client.post(
        "/api/v1/memory/upload",
        data={
            "workspace_id": str(app.config["TEST_WORKSPACE_ID"]),
            "title": "Agent full document",
            "memory_type": "technical_notes",
            "tags": "agent,document",
            "confirmed": "true",
            "ingest_mode": "full",
            "uploads": (BytesIO(b"Line one\nLine two\n"), "notes.txt"),
        },
        headers=api_headers,
        content_type="multipart/form-data",
    )
    assert res.status_code == 201
    payload = res.get_json()
    assert payload["count"] == 1
    memory = payload["memories"][0]
    assert memory["title"] == "Agent full document"
    assert "Line one\nLine two" in memory["content"]
    assert memory["source"] == "upload"
    assert memory["assets"][0]["url"]
    with app.app_context():
        stored_path = MemoryAsset.query.filter_by(memory_id=memory["id"]).one().stored_path
    Path(stored_path).unlink(missing_ok=True)


def test_agent_upload_document_as_chunks(client, app, api_headers):
    text = "\n".join(f"line {index} alpha beta gamma" for index in range(120)).encode()
    res = client.post(
        "/api/v1/memory/upload",
        data={
            "workspace_id": str(app.config["TEST_WORKSPACE_ID"]),
            "title": "Agent chunked document",
            "memory_type": "technical_notes",
            "ingest_mode": "chunks",
            "chunk_size": "500",
            "uploads": (BytesIO(text), "large.txt"),
        },
        headers=api_headers,
        content_type="multipart/form-data",
    )
    assert res.status_code == 201
    payload = res.get_json()
    assert payload["count"] > 1
    assert all("chunk" in memory["title"] for memory in payload["memories"])
    assert all(memory["assets"] for memory in payload["memories"])
    with app.app_context():
        paths = {asset.stored_path for asset in MemoryAsset.query.filter(MemoryAsset.memory_id.in_([memory["id"] for memory in payload["memories"]])).all()}
    for path in paths:
        Path(path).unlink(missing_ok=True)


def test_agent_replace_uploaded_document_asset(client, app, api_headers):
    upload = client.post(
        "/api/v1/memory/upload",
        data={
            "workspace_id": str(app.config["TEST_WORKSPACE_ID"]),
            "title": "Replaceable document",
            "memory_type": "technical_notes",
            "confirmed": "true",
            "ingest_mode": "full",
            "uploads": (BytesIO(b"old file content"), "old.txt"),
        },
        headers=api_headers,
        content_type="multipart/form-data",
    )
    assert upload.status_code == 201
    memory = upload.get_json()["memories"][0]
    old_url = memory["assets"][0]["url"]
    with app.app_context():
        asset = MemoryAsset.query.filter_by(memory_id=memory["id"]).one()
        old_token = asset.public_token
        old_path = asset.stored_path

    replace = client.post(
        f"/api/v1/memory/{memory['id']}/asset/replace",
        data={
            "title": "Replaced document",
            "file": (BytesIO(b"new file content"), "new.txt"),
        },
        headers=api_headers,
        content_type="multipart/form-data",
    )
    assert replace.status_code == 200
    payload = replace.get_json()
    assert payload["memory"]["id"] == memory["id"]
    assert payload["memory"]["title"] == "Replaced document"
    assert "new file content" in payload["memory"]["content"]
    assert "old file content" not in payload["memory"]["content"]
    assert payload["asset"]["url"] == old_url
    with app.app_context():
        asset = MemoryAsset.query.filter_by(memory_id=memory["id"]).one()
        assert asset.public_token == old_token
        assert asset.original_filename == "new.txt"
        new_path = asset.stored_path
        assert old_path != new_path
        assert not Path(old_path).exists()
    asset_res = client.get(old_url)
    assert asset_res.status_code == 200
    assert asset_res.data == b"new file content"
    Path(new_path).unlink(missing_ok=True)


def test_compact_agent_search_includes_asset_urls(client, app, api_headers):
    upload = client.post(
        "/api/v1/memory/upload",
        data={
            "workspace_id": str(app.config["TEST_WORKSPACE_ID"]),
            "title": "Searchable image asset",
            "memory_type": "vision",
            "tags": "searchable,image",
            "confirmed": "true",
            "uploads": (BytesIO(b"image-bytes"), "searchable.jpg"),
        },
        headers=api_headers,
        content_type="multipart/form-data",
    )
    assert upload.status_code == 201
    memory = upload.get_json()["memories"][0]
    search = client.get(
        f"/api/v1/search?workspace_id={app.config['TEST_WORKSPACE_ID']}&query=searchable%20image&mode=agent&compact=true",
        headers=api_headers,
    )
    assert search.status_code == 200
    matches = [item for item in search.get_json()["results"] if item["memory_id"] == memory["id"]]
    assert matches
    assert matches[0]["assets"]
    assert matches[0]["assets"][0]["url"]
    with app.app_context():
        stored_path = MemoryAsset.query.filter_by(memory_id=memory["id"]).one().stored_path
    Path(stored_path).unlink(missing_ok=True)


def test_asset_url_uses_public_base_url_setting(client, app, api_headers):
    with app.app_context():
        SettingsService.update({"public_base_url": "https://human-brain.ibnet.lan"})
    upload = client.post(
        "/api/v1/memory/upload",
        data={
            "workspace_id": str(app.config["TEST_WORKSPACE_ID"]),
            "title": "External image asset",
            "memory_type": "vision",
            "confirmed": "true",
            "uploads": (BytesIO(b"image-bytes"), "external.jpg"),
        },
        headers=api_headers,
        content_type="multipart/form-data",
        base_url="http://127.0.0.1:9393",
    )
    assert upload.status_code == 201
    memory = upload.get_json()["memories"][0]
    assert memory["assets"][0]["url"].startswith("https://human-brain.ibnet.lan/memory-assets/")
    assert "https://human-brain.ibnet.lan/memory-assets/" in memory["content"]
    with app.app_context():
        stored_path = MemoryAsset.query.filter_by(memory_id=memory["id"]).one().stored_path
    Path(stored_path).unlink(missing_ok=True)


def test_agent_can_list_session_jobs(client, app, api_headers):
    start = client.post(
        "/api/v1/session/start",
        json={"workspace_id": app.config["TEST_WORKSPACE_ID"], "title": "Job list test"},
        headers=api_headers,
    )
    assert start.status_code == 201
    session_id = start.get_json()["session_id"]
    consolidate = client.post("/api/v1/session/consolidate", json={"session_id": session_id}, headers=api_headers)
    assert consolidate.status_code == 202
    jobs = client.get(f"/api/v1/jobs?workspace_id={app.config['TEST_WORKSPACE_ID']}", headers=api_headers)
    assert jobs.status_code == 200
    assert any(job["id"] == consolidate.get_json()["job_id"] for job in jobs.get_json()["jobs"])


def test_agent_session_id_auto_captures_api_exchange(client, app, api_headers):
    start = client.post(
        "/api/v1/session/start",
        json={"workspace_id": app.config["TEST_WORKSPACE_ID"], "title": "Auto capture"},
        headers=api_headers,
    )
    session_id = start.get_json()["session_id"]
    search = client.post(
        "/api/v1/memory/search",
        json={"workspace_id": app.config["TEST_WORKSPACE_ID"], "session_id": session_id, "query": "Πες μου για την εικόνα"},
        headers=api_headers,
    )
    assert search.status_code == 200
    with app.app_context():
        messages = SessionMessage.query.filter_by(session_id=session_id).order_by(SessionMessage.id.asc()).all()
        assert [message.role for message in messages] == ["user", "assistant"]
        assert "Πες μου για την εικόνα" in messages[0].content
        assert "results" in messages[1].content


def test_agent_logs_page_renders_empty_state(client):
    client.post("/login", data={"email": "admin@example.com", "password": "password"})
    res = client.get("/agent-logs")
    assert res.status_code == 200
    assert b"Agent API Logs" in res.data


def test_agent_logs_keep_unicode_readable(app, tmp_path):
    with app.app_context():
        service = AgentLogService()
        service.log_dir = tmp_path
        service.write(
            {
                "method": "POST",
                "path": "/api/v1/memory/search",
                "body": {"query": "Πες μου για την εικόνα"},
                "response": {"results": [{"content": "Καλημέρα"}]},
            }
        )
        assert "Πες μου" in (tmp_path / "agent_api.jsonl").read_text(encoding="utf-8")

        old_row = {
            "ts": "2026-05-31T16:01:42",
            "level": "info",
            "method": "POST",
            "path": "/api/v1/memory/search",
            "body": json.dumps({"query": "Πες μου για την εικόνα"}),
            "response": json.dumps({"results": [{"content": "Καλημέρα"}]}),
        }
        (tmp_path / "agent_api_escaped.jsonl").write_text(
            json.dumps(old_row, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        logs = service.items(query="Πες", page=1, per_page=10)
        assert logs["total"] == 2
        assert logs["items"][0]["_detail"]["body"]["query"] == "Πες μου για την εικόνα"


def test_viewer_cannot_create_agent(client, app):
    with app.app_context():
        admin = User.query.filter_by(email="admin@example.com").first()
        admin.role = "viewer"
        db.session.commit()
    client.post("/login", data={"email": "admin@example.com", "password": "password"})
    res = client.post("/agents", data={"name": "Blocked"}, follow_redirects=False)
    assert res.status_code == 403


def test_backup_and_agent_export(client, app):
    client.post("/login", data={"email": "admin@example.com", "password": "password"})
    backup = client.post("/backups/create", follow_redirects=True)
    assert backup.status_code == 200
    with app.app_context():
        backups = BackupService().list_backups()
        assert backups
        assert backups[0].suffix == ".zip"
    export = client.get(f"/agents/{app.config['TEST_AGENT_ID']}/export")
    assert export.status_code == 200
    assert "attachment" in export.headers.get("Content-Disposition", "")


def test_restore_zip_backup_and_delete_memory(client, app, api_headers):
    client.post("/login", data={"email": "admin@example.com", "password": "password"})
    with app.app_context():
        backup_path = BackupService().create_backup()["path"]
    with open(backup_path, "rb") as handle:
        restore = client.post(
            "/backups/restore",
            data={"backup": (handle, "restore.zip")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
    assert restore.status_code == 200
    payload = {
        "agent_id": app.config["TEST_AGENT_ID"],
        "workspace_id": app.config["TEST_WORKSPACE_ID"],
        "content": "Delete me permanently.",
        "memory_type": "long-term",
    }
    memory_id = client.post("/api/v1/memory/add", json=payload, headers=api_headers).get_json()["memory"]["id"]
    deleted = client.post(f"/memories/{memory_id}/delete-hard", follow_redirects=True)
    assert deleted.status_code == 200
    with app.app_context():
        assert db.session.get(Memory, memory_id) is None


def test_bulk_delete_memories_from_current_page(client, app, api_headers):
    client.post("/login", data={"email": "admin@example.com", "password": "password"})
    payload = {
        "agent_id": app.config["TEST_AGENT_ID"],
        "workspace_id": app.config["TEST_WORKSPACE_ID"],
        "memory_type": "long-term",
    }
    first = client.post("/api/v1/memory/add", json={**payload, "content": "Bulk delete memory one."}, headers=api_headers).get_json()["memory"]["id"]
    second = client.post("/api/v1/memory/add", json={**payload, "content": "Bulk delete memory two."}, headers=api_headers).get_json()["memory"]["id"]
    third = client.post("/api/v1/memory/add", json={**payload, "content": "Keep this memory."}, headers=api_headers).get_json()["memory"]["id"]
    page = client.get("/memories")
    assert page.status_code == 200
    assert b'id="bulkMemoryDeleteForm"' in page.data
    assert b'id="confirmActionModal"' in page.data
    assert b"confirm(" not in page.data
    deleted = client.post(
        "/memories/delete-hard-bulk",
        data={"memory_ids": [str(first), str(second)]},
        follow_redirects=True,
    )
    assert deleted.status_code == 200
    with app.app_context():
        assert db.session.get(Memory, first) is None
        assert db.session.get(Memory, second) is None
        assert db.session.get(Memory, third) is not None


def test_memory_add_search_delete(client, app, api_headers):
    payload = {
        "agent_id": app.config["TEST_AGENT_ID"],
        "workspace_id": app.config["TEST_WORKSPACE_ID"],
        "content": "The production database uses PostgreSQL.",
        "memory_type": "technical_notes",
        "confirmed": True,
    }
    add = client.post("/api/v1/memory/add", json=payload, headers=api_headers)
    assert add.status_code == 201
    memory_id = add.get_json()["memory"]["id"]
    search = client.post("/api/v1/memory/search", json={**payload, "query": "database"}, headers=api_headers)
    assert search.status_code == 200
    delete = client.post("/api/v1/memory/delete", json={**payload, "id": memory_id}, headers=api_headers)
    assert delete.status_code == 200


def test_web_semantic_search_returns_memory(client, app, api_headers):
    base = {"agent_id": app.config["TEST_AGENT_ID"], "workspace_id": app.config["TEST_WORKSPACE_ID"]}
    client.post(
        "/api/v1/memory/add",
        json={**base, "content": "Production deployments use PostgreSQL for the database.", "memory_type": "technical_notes", "confirmed": True},
        headers=api_headers,
    )
    client.post("/login", data={"email": "admin@example.com", "password": "password"})
    res = client.post("/web/search", json={**base, "query": "production database", "top_k": 10})
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["results"]
    assert "PostgreSQL" in payload["results"][0]["memory"]["content"]


def test_reranker_disabled_adds_timing_without_reranking(client, app, api_headers):
    base = {"agent_id": app.config["TEST_AGENT_ID"], "workspace_id": app.config["TEST_WORKSPACE_ID"]}
    client.post(
        "/api/v1/memory/add",
        json={**base, "content": "PostgreSQL is used for production storage.", "memory_type": "technical_notes", "confirmed": True},
        headers=api_headers,
    )
    search = client.post("/api/v1/memory/search", json={**base, "query": "production storage", "include_timing": True}, headers=api_headers)
    assert search.status_code == 200
    payload = search.get_json()
    assert payload["timing"]["reranker_enabled"] is False
    assert payload["timing"]["reranker_used"] is False
    assert payload["results"][0]["reranker_score"] is None
    assert "final_score" in payload["results"][0]


def test_cross_encoder_reranker_reorders_candidates(client, app, api_headers, monkeypatch):
    base = {"agent_id": app.config["TEST_AGENT_ID"], "workspace_id": app.config["TEST_WORKSPACE_ID"]}
    first = client.post(
        "/api/v1/memory/add",
        json={**base, "title": "General database note", "content": "Storage notes mention backups.", "memory_type": "technical_notes", "confirmed": True},
        headers=api_headers,
    ).get_json()["memory"]["id"]
    second = client.post(
        "/api/v1/memory/add",
        json={**base, "title": "PostgreSQL production note", "content": "PostgreSQL is the production database.", "memory_type": "technical_notes", "confirmed": True},
        headers=api_headers,
    ).get_json()["memory"]["id"]
    with app.app_context():
        SettingsService.update(
            {
                "reranker_enabled": True,
                "reranker_provider": "cross_encoder",
                "reranker_default_mode": "always",
                "reranker_top_n": 5,
                "reranker_return_k": 5,
                "reranker_timeout_ms": 1000,
            }
        )

    def fake_scores(self, query, candidates, settings, wait_for_model=False):
        return {item["memory"].id: (0.95 if item["memory"].id == second else 0.1) for item in candidates}, {}

    def fake_search(self, workspace_id, query_vector, top_k, timing=None):
        return [
            {"memory_id": first, "semantic_score": 0.55, "vector_id": 1, "raw_score": 0.55},
            {"memory_id": second, "semantic_score": 0.52, "vector_id": 2, "raw_score": 0.52},
        ]

    monkeypatch.setattr(RerankerService, "_cross_encoder_scores", fake_scores)
    monkeypatch.setattr("app.services.faiss_service.FaissService.search", fake_search)
    RerankerService._cross_encoder = object()
    RerankerService._cross_encoder_key = ("BAAI/bge-reranker-base", "cpu")
    search = client.post(
        "/api/v1/memory/search",
        json={**base, "query": "database", "include_timing": True, "top_k": 5, "min_semantic_score": 0.0},
        headers=api_headers,
    )
    assert search.status_code == 200
    payload = search.get_json()
    assert payload["timing"]["reranker_used"] is True, json.dumps(payload["timing"], sort_keys=True)
    assert payload["results"][0]["memory"]["id"] == second
    assert payload["results"][0]["reranker_score"] == 0.95
    assert payload["results"][0]["retrieved_by"] == "reranked"
    assert first in [item["memory"]["id"] for item in payload["results"]]


def test_semantic_search_does_not_union_keyword_candidates_when_faiss_has_hits(client, app, api_headers, monkeypatch):
    base = {"agent_id": app.config["TEST_AGENT_ID"], "workspace_id": app.config["TEST_WORKSPACE_ID"]}
    username_id = client.post(
        "/api/v1/memory/add",
        json={**base, "title": "UserName", "content": "User name is John in Greek Yannis.", "memory_type": "long-term", "confirmed": True},
        headers=api_headers,
    ).get_json()["memory"]["id"]
    work_id = client.post(
        "/api/v1/memory/add",
        json={**base, "title": "User work", "content": "John's job is Information Security Manager at Unixfor.", "memory_type": "long-term", "confirmed": True},
        headers=api_headers,
    ).get_json()["memory"]["id"]

    def fake_search(self, workspace_id, query_vector, top_k, timing=None):
        return [{"memory_id": username_id, "semantic_score": 0.6, "vector_id": 1, "raw_score": 0.6}]

    monkeypatch.setattr("app.services.faiss_service.FaissService.search", fake_search)
    search = client.post(
        "/api/v1/memory/search",
        json={**base, "query": "what job john have", "include_timing": True, "top_k": 10},
        headers=api_headers,
    )
    assert search.status_code == 200
    ids = [item["memory"]["id"] for item in search.get_json()["results"]]
    assert username_id in ids
    assert work_id not in ids


def test_keyword_search_is_fallback_only_when_faiss_has_no_hits(client, app, api_headers, monkeypatch):
    base = {"agent_id": app.config["TEST_AGENT_ID"], "workspace_id": app.config["TEST_WORKSPACE_ID"]}
    memory_id = client.post(
        "/api/v1/memory/add",
        json={**base, "title": "PostgreSQL task", "content": "Add nightly PostgreSQL backups.", "memory_type": "task", "confirmed": True},
        headers=api_headers,
    ).get_json()["memory"]["id"]

    def fake_search(self, workspace_id, query_vector, top_k, timing=None):
        return []

    monkeypatch.setattr("app.services.faiss_service.FaissService.search", fake_search)
    search = client.post(
        "/api/v1/memory/search",
        json={**base, "query": "postgresql backups", "include_timing": True, "top_k": 10},
        headers=api_headers,
    )
    assert search.status_code == 200
    ids = [item["memory"]["id"] for item in search.get_json()["results"]]
    assert memory_id in ids


def test_weak_keyword_only_candidate_is_filtered_when_semantic_is_low(client, app, api_headers, monkeypatch):
    base = {"agent_id": app.config["TEST_AGENT_ID"], "workspace_id": app.config["TEST_WORKSPACE_ID"]}
    username_id = client.post(
        "/api/v1/memory/add",
        json={**base, "title": "UserName", "content": "User name is John in Greek Yannis.", "memory_type": "long-term", "confirmed": True},
        headers=api_headers,
    ).get_json()["memory"]["id"]
    work_id = client.post(
        "/api/v1/memory/add",
        json={**base, "title": "John's Work", "content": "John works at Unixfor as an Information Security Manager.", "memory_type": "long-term", "confirmed": True},
        headers=api_headers,
    ).get_json()["memory"]["id"]

    def fake_search(self, workspace_id, query_vector, top_k, timing=None):
        return [{"memory_id": username_id, "semantic_score": 0.6, "vector_id": 1, "raw_score": 0.6}]

    monkeypatch.setattr("app.services.faiss_service.FaissService.search", fake_search)
    search = client.post(
        "/api/v1/memory/search",
        json={**base, "query": "what is john's favorite food", "include_timing": True, "top_k": 10},
        headers=api_headers,
    )
    assert search.status_code == 200
    ids = [item["memory"]["id"] for item in search.get_json()["results"]]
    assert username_id in ids
    assert work_id not in ids


def test_memory_correlation_service(client, app, api_headers):
    base = {"agent_id": app.config["TEST_AGENT_ID"], "workspace_id": app.config["TEST_WORKSPACE_ID"]}
    first = client.post("/api/v1/memory/add", json={**base, "content": "Apple detected by YOLO in kitchen.", "memory_type": "vision", "tags": ["apple", "vision"]}, headers=api_headers).get_json()["memory"]["id"]
    second = client.post("/api/v1/memory/add", json={**base, "content": "User prefers apples for snacks.", "memory_type": "preferences", "tags": ["apple", "preference"]}, headers=api_headers).get_json()["memory"]["id"]
    with app.app_context():
        correlations = CorrelationService().for_memory(first)
        assert correlations
        assert any(second in [item.source_memory_id, item.target_memory_id] for item in correlations)
    search = client.post(
        "/api/v1/memory/search",
        json={**base, "query": "apple", "include_vector_details": True, "include_correlations": True},
        headers=api_headers,
    )
    assert search.status_code == 200
    result = search.get_json()["results"][0]
    assert "vector_score" in result
    assert "vector" in result
    assert "correlations" in result
    direct = client.get(f"/api/v1/memory/{first}/correlations?workspace_id={base['workspace_id']}", headers=api_headers)
    assert direct.status_code == 200
    assert direct.get_json()["correlations"]


def test_generic_upload_metadata_does_not_correlate_irrelevant_memories(client, app, api_headers):
    base = {"agent_id": app.config["TEST_AGENT_ID"], "workspace_id": app.config["TEST_WORKSPACE_ID"]}
    image = client.post(
        "/api/v1/memory/add",
        json={
            **base,
            "title": "Messier 51",
            "content": "Uploaded image m51.jpg stored path local visual vector dominant color green.",
            "memory_type": "vision",
            "tags": ["green", "image", "jpg", "m51", "nebula", "upload", "visual"],
        },
        headers=api_headers,
    ).get_json()["memory"]["id"]
    pdf = client.post(
        "/api/v1/memory/add",
        json={
            **base,
            "title": "Unixfor Company Information - chunk 1",
            "content": "Uploaded document company kiosks pdf local mime path stored type.",
            "memory_type": "long-term",
            "tags": ["company", "kiosks", "pdf", "unixfor", "upload"],
        },
        headers=api_headers,
    ).get_json()["memory"]["id"]
    with app.app_context():
        correlations = CorrelationService().for_memory(image)
        assert all(pdf not in [item.source_memory_id, item.target_memory_id] for item in correlations)


def test_vision_save_current_detection_attaches_snapshot_asset(client, app, api_headers):
    with app.app_context():
        SettingsService.update({"snapshot_storage_enabled": True})
        VisionRuntime.last_detection = {
            "timestamp": "2026-05-31T20:00:00",
            "objects": [{"label": "person", "confidence": 0.91}, {"label": "cup", "confidence": 0.76}],
        }
        VisionRuntime.last_snapshot = b"snapshot-bytes"
    res = client.post(
        "/api/v1/vision/save-current",
        json={"workspace_id": app.config["TEST_WORKSPACE_ID"]},
        headers=api_headers,
    )
    assert res.status_code == 201
    memory = res.get_json()["memory"]
    assert memory["memory_type"] == "vision"
    assert {"person", "cup", "camera"}.issubset(set(memory["tags"]))
    assert memory["assets"]
    assert "Snapshot URL:" in memory["content"]
    with app.app_context():
        asset = MemoryAsset.query.filter_by(memory_id=memory["id"]).one()
        assert asset.asset_type == "image"
        assert asset.asset_metadata["objects"][0]["label"] == "person"
        Path(asset.stored_path).unlink(missing_ok=True)


def test_vision_auto_save_uses_interval_for_same_detection(client, app):
    with app.app_context():
        SettingsService.update({"vision_auto_save": True, "snapshot_storage_enabled": True, "vision_auto_save_interval_seconds": 30})
        VisionRuntime.last_detection = {
            "timestamp": "2026-05-31T20:00:00",
            "objects": [{"label": "keyboard", "confidence": 0.88}],
        }
        VisionRuntime.last_snapshot = b"snapshot-bytes"
        VisionRuntime.last_auto_saved_signature = None
        VisionRuntime.last_auto_saved_at = None
        service = VisionService()
        service._maybe_auto_save_current_detection(b"snapshot-bytes")
        service._maybe_auto_save_current_detection(b"snapshot-bytes")
        memories = Memory.query.filter(Memory.title.like("Vision detected keyboard%")).all()
        assert len(memories) == 1
        asset = MemoryAsset.query.filter_by(memory_id=memories[0].id).one()
        Path(asset.stored_path).unlink(missing_ok=True)


def test_vision_status_includes_yolo_device(client, app):
    with app.app_context():
        SettingsService.update({"yolo_device": "cuda:0"})
        status = VisionService().status()
        assert status["device"] == "cuda:0"


def test_yolo26_settings_are_sanitized_to_default(app):
    with app.app_context():
        SettingsService.update({"yolo_model": "models/yolo26x.pt", "vision_models": ["models/yolo26x.pt"]})
        assert SettingsService.get("yolo_model") == "models/yolov8n.pt"
        assert SettingsService.get("vision_models") == ["models/yolov8n.pt"]


def test_vision_model_error_message_explains_yolo26_runtime_mismatch(app):
    with app.app_context():
        message = VisionService()._model_error_message("models/yolo26x.pt", AttributeError("Can't get attribute 'C3k2'"))
        assert "requires a newer Ultralytics" in message
        assert "models/yolov8n.pt" in message


def test_web_memory_and_session_workflows(client, app):
    client.post("/login", data={"email": "admin@example.com", "password": "password"})
    memory = client.post(
        "/memories",
        data={
            "agent_id": app.config["TEST_AGENT_ID"],
            "workspace_id": app.config["TEST_WORKSPACE_ID"],
            "title": "UI memory",
            "content": "UI can save memories.",
            "memory_type": "long-term",
            "tags": "ui,test",
            "importance_score": "0.6",
            "trust_score": "0.7",
            "sensitivity_level": "normal",
            "confirmed": "on",
        },
        follow_redirects=True,
    )
    assert memory.status_code == 200
    session = client.post(
        "/sessions",
        data={"agent_id": app.config["TEST_AGENT_ID"], "workspace_id": app.config["TEST_WORKSPACE_ID"], "title": "UI Session"},
        follow_redirects=False,
    )
    assert session.status_code == 302


def test_session_replay_and_web_consolidate(client, app):
    client.post("/login", data={"email": "admin@example.com", "password": "password"})
    session = client.post(
        "/sessions",
        data={"agent_id": app.config["TEST_AGENT_ID"], "workspace_id": app.config["TEST_WORKSPACE_ID"], "title": "Replay Session"},
        follow_redirects=False,
    )
    session_id = int(session.headers["Location"].rstrip("/").split("/")[-1])
    message = client.post(
        f"/sessions/{session_id}/message",
        data={"role": "user", "content": "Decision: use PostgreSQL for production."},
        follow_redirects=True,
    )
    assert b"PostgreSQL" in message.data
    replay = client.get(f"/sessions/{session_id}")
    assert replay.status_code == 200
    assert b"Replay Session" in replay.data
    consolidated = client.post(f"/sessions/{session_id}/consolidate", follow_redirects=True)
    assert consolidated.status_code == 200
    with app.app_context():
        from app.models import ConsolidationJob

        job = ConsolidationJob.query.filter_by(session_id=session_id).first()
        assert job is not None
        assert job.status in {"queued", "completed"}


def test_workspace_isolation(client, app, api_headers):
    with app.app_context():
        other = Workspace(name="Other")
        db.session.add(other)
        db.session.commit()
        other_id = other.id
    res = client.post(
        "/api/v1/memory/search",
        json={"agent_id": app.config["TEST_AGENT_ID"], "workspace_id": other_id, "query": "x"},
        headers=api_headers,
    )
    assert res.status_code == 403


def test_duplicates_page_renders_duplicate_groups(client, app, api_headers):
    base = {"agent_id": app.config["TEST_AGENT_ID"], "workspace_id": app.config["TEST_WORKSPACE_ID"]}
    client.post(
        "/api/v1/memory/add",
        json={**base, "content": "Alpha bravo charlie delta echo foxtrot golf hotel note a.", "memory_type": "technical_notes"},
        headers=api_headers,
    )
    client.post(
        "/api/v1/memory/add",
        json={**base, "content": "Alpha bravo charlie delta echo foxtrot golf hotel note b.", "memory_type": "technical_notes"},
        headers=api_headers,
    )
    client.post("/login", data={"email": "admin@example.com", "password": "password"})
    res = client.get("/duplicates")
    assert res.status_code == 200
    assert b"Potential Duplicate Groups" in res.data
    assert b"2 memories" in res.data
    assert b"Alpha bravo charlie delta echo foxtrot golf hotel note" in res.data


def test_session_consolidation_context_and_audit(client, app, api_headers):
    base = {"agent_id": app.config["TEST_AGENT_ID"], "workspace_id": app.config["TEST_WORKSPACE_ID"]}
    session_id = client.post("/api/v1/session/start", json=base, headers=api_headers).get_json()["session_id"]
    client.post("/api/v1/session/add-message", json={"session_id": session_id, "role": "user", "content": "Decision: use Redis for Celery."}, headers=api_headers)
    with app.app_context():
        from app.models import ConsolidationJob

        job = ConsolidationJob(session_id=session_id, **base)
        db.session.add(job)
        db.session.commit()
        consolidate_session_task(job.id)
        assert Memory.query.count() >= 1
        assert AuditLog.query.count() >= 1
    ctx = client.post("/api/v1/context/build", json={**base, "prompt": "What queue do we use?", "top_k": 3}, headers=api_headers)
    assert ctx.status_code == 200


def test_sensitive_memory_filtering(client, app, api_headers):
    base = {"agent_id": app.config["TEST_AGENT_ID"], "workspace_id": app.config["TEST_WORKSPACE_ID"]}
    client.post("/api/v1/memory/add", json={**base, "content": "secret token is not injectable", "memory_type": "security_findings", "sensitivity_level": "secret"}, headers=api_headers)
    ctx = client.post("/api/v1/context/build", json={**base, "prompt": "token", "top_k": 3, "sensitivity_policy": "strict"}, headers=api_headers)
    assert "secret token" not in ctx.get_json()["context"]

def test_faiss_rebuild(client, app, api_headers):
    from app.services.embedding_service import EmbeddingService
    from app.services.faiss_service import FaissService

    with app.app_context():
        status = FaissService(app.config["FAISS_INDEX_DIR"]).rebuild(app.config["TEST_WORKSPACE_ID"], EmbeddingService(app.config["EMBEDDING_MODEL"]))
        assert "count" in status


def test_unixfor_semantic_search_uses_faiss_vectors(client, app, api_headers):
    base = {"agent_id": app.config["TEST_AGENT_ID"], "workspace_id": app.config["TEST_WORKSPACE_ID"]}
    content = (
        "For more detailed information about Unixfor's products, services, and company background, "
        "please visit their official website at https://www.unixfor.gr/."
    )
    client.post(
        "/api/v1/memory/add",
        json={
            **base,
            "title": "Unixfor official website",
            "content": content,
            "memory_type": "long-term",
            "tags": ["unixfor", "website", "company"],
            "confirmed": True,
        },
        headers=api_headers,
    )
    for query in ["what is unixfor's web address", "where can I find unixfor online", "official site for unixfor"]:
        res = client.post(
            "/api/v1/memory/search",
            json={**base, "query": query, "top_k": 3, "include_vector_details": True, "include_timing": True},
            headers=api_headers,
        )
        assert res.status_code == 200
        payload = res.get_json()
        assert payload["timing"]["elapsed_ms"] < 300
        assert "embedding_ms" in payload["timing"]
        assert "faiss_search_ms" in payload["timing"]
        assert "db_lookup_ms" in payload["timing"]
        assert "serialization_ms" in payload["timing"]
        match = next((item for item in payload["results"] if "https://www.unixfor.gr/" in item["memory"]["content"]), None)
        assert match is not None
        assert match["semantic_score"] > 0
        assert match["vector_score"] > 0
        assert match["vector"]["vector_id"] is not None
        assert match["vector"]["retrieved_by"] == "semantic_vector"


def test_vector_health_endpoint(client, app, api_headers):
    base = {"agent_id": app.config["TEST_AGENT_ID"], "workspace_id": app.config["TEST_WORKSPACE_ID"]}
    client.post(
        "/api/v1/memory/add",
        json={**base, "content": "Vector health should count indexed memories.", "memory_type": "technical_notes"},
        headers=api_headers,
    )
    res = client.get("/api/v1/vector/health", headers=api_headers)
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["faiss_index_type"] == "IndexIDMap2(IndexFlatIP)"
    assert payload["total_vectors"] >= 1
    assert payload["memories_without_vectors"] == 0
    warmup = client.post("/api/v1/vector/warmup", headers=api_headers)
    assert warmup.status_code == 200
    perf = client.get("/api/v1/performance", headers=api_headers)
    assert perf.status_code == 200
    assert "search_latency" in perf.get_json()


def test_get_search_compact_mode(client, app, api_headers):
    base = {"agent_id": app.config["TEST_AGENT_ID"], "workspace_id": app.config["TEST_WORKSPACE_ID"]}
    client.post(
        "/api/v1/memory/add",
        json={**base, "content": "Compact search should return small agent-ready payloads.", "memory_type": "technical_notes"},
        headers=api_headers,
    )
    res = client.get(
        f"/api/v1/search?workspace_id={base['workspace_id']}&query=agent-ready payloads&compact=true&mode=agent",
        headers=api_headers,
    )
    assert res.status_code == 200
    item = res.get_json()["results"][0]
    assert "memory_id" in item
    assert "semantic_score" in item
    assert "assets" not in item
    assert "created_at" not in item
