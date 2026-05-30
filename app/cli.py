import json
import shutil
from datetime import datetime
from pathlib import Path
from time import perf_counter

import click
from flask import current_app

from app.extensions import db
from app.models import Agent, ApiKey, Memory, Session, SessionMessage, User, Workspace, WorkspaceAgent
from app.services.admin_service import AdminService
from app.services.correlation_service import CorrelationService
from app.services.memory_service import MemoryService
from app.services.embedding_service import EmbeddingService
from app.services.faiss_service import FaissService
from app.services.settings_service import SettingsService


def register_commands(app):
    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    @click.option("--name", default="Administrator")
    def create_admin(email, password, name):
        user = User(email=email.lower(), name=name, role="admin")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Created admin {email}")

    @app.cli.command("seed-demo-data")
    def seed_demo_data():
        SettingsService.ensure_defaults()
        workspace = Workspace.query.first() or Workspace(name="Default Workspace", description="Local private AI memory workspace")
        db.session.add(workspace)
        db.session.flush()
        agent = Agent.query.first() or Agent(name="Demo Agent", description="Example AI agent", permissions={"memory": "rw"})
        db.session.add(agent)
        db.session.flush()
        if not WorkspaceAgent.query.filter_by(workspace_id=workspace.id, agent_id=agent.id).first():
            db.session.add(WorkspaceAgent(workspace_id=workspace.id, agent_id=agent.id, permissions={"memory": "rw"}))
        if not ApiKey.query.filter_by(agent_id=agent.id).first():
            raw, prefix, key_hash = ApiKey.create_token()
            db.session.add(ApiKey(agent_id=agent.id, name="Demo key", prefix=prefix, key_hash=key_hash))
            click.echo(f"Demo API key: {raw}")
        db.session.commit()
        click.echo("Seeded demo workspace and agent")

    @app.cli.command("seed-sample-data")
    @click.option("--count", default=100, type=int)
    def seed_sample_data(count):
        SettingsService.ensure_defaults()
        workspace = Workspace(name="Sample Workspace", description="Generated sample data for Human-Brain testing")
        db.session.add(workspace)
        db.session.flush()
        agents = []
        for name in ["Research Agent", "Ops Agent", "Vision Agent", "Security Agent"]:
            agent = Agent(name=name, description=f"Sample {name}", permissions={"memory": "rw", "context": "read"})
            db.session.add(agent)
            db.session.flush()
            db.session.add(WorkspaceAgent(workspace_id=workspace.id, agent_id=agent.id, permissions={"memory": "rw"}))
            agents.append(agent)
        db.session.commit()
        memory_types = ["facts", "decisions", "tasks", "preferences", "technical_notes", "project_context", "security_findings", "vision"]
        topics = ["PostgreSQL", "Redis", "YOLO apple detection", "backup schedule", "agent firewall", "workspace isolation", "FAISS index", "session replay"]
        for idx in range(count):
            agent = agents[idx % len(agents)]
            topic = topics[idx % len(topics)]
            memory_type = memory_types[idx % len(memory_types)]
            sensitivity = "high" if memory_type == "security_findings" else "normal"
            MemoryService().add_memory(
                {
                    "agent_id": agent.id,
                    "workspace_id": workspace.id,
                    "title": f"Sample {memory_type} {idx + 1}",
                    "content": f"Sample memory {idx + 1}: {topic} relates to {memory_type} and project testing.",
                    "memory_type": memory_type,
                    "tags": ["sample", topic.lower().replace(" ", "-"), memory_type],
                    "importance_score": 0.4 + ((idx % 5) * 0.1),
                    "trust_score": 0.5 + ((idx % 4) * 0.1),
                    "sensitivity_level": sensitivity,
                    "confirmed": idx % 3 != 0,
                    "source": "sample_seed",
                },
                actor_type="system",
            )
        for idx in range(8):
            agent = agents[idx % len(agents)]
            session = Session(agent_id=agent.id, workspace_id=workspace.id, title=f"Sample Session {idx + 1}", status="ended")
            db.session.add(session)
            db.session.flush()
            db.session.add(SessionMessage(session_id=session.id, role="user", content=f"Decision: sample session {idx + 1} uses {topics[idx % len(topics)]}."))
            db.session.add(SessionMessage(session_id=session.id, role="assistant", content=f"Task: follow up on {topics[(idx + 1) % len(topics)]}."))
        db.session.commit()
        CorrelationService().rebuild_workspace(workspace.id)
        click.echo(f"Seeded {count} sample memories plus agents, sessions, correlations in workspace {workspace.id}")

    @app.cli.command("purge-sample-data")
    def purge_sample_data():
        sample_workspaces = Workspace.query.filter(Workspace.name.like("Sample%")).all()
        for workspace in sample_workspaces:
            AdminService.delete_workspace(workspace.id)
        sample_memories = Memory.query.filter_by(source="sample_seed").all()
        for memory in sample_memories:
            AdminService.delete_memory(memory.id)
        db.session.commit()
        click.echo("Purged sample data")

    @app.cli.command("rebuild-index")
    @click.option("--workspace-id", type=int)
    def rebuild_index(workspace_id):
        workspace_ids = [workspace_id] if workspace_id else [w.id for w in Workspace.query.all()]
        service = FaissService(current_app.config["FAISS_INDEX_DIR"])
        embeddings = EmbeddingService(current_app.config["EMBEDDING_MODEL"])
        for wid in workspace_ids:
            click.echo(json.dumps(service.rebuild(wid, embeddings)))

    @app.cli.command("vector-health")
    def vector_health():
        service = FaissService(current_app.config["FAISS_INDEX_DIR"])
        click.echo(json.dumps(service.health(), indent=2))

    @app.cli.command("test-search")
    @click.argument("query")
    @click.option("--workspace-id", type=int)
    @click.option("--agent-id", type=int)
    @click.option("--top-k", default=5, type=int)
    def test_search(query, workspace_id, agent_id, top_k):
        workspace = db.session.get(Workspace, workspace_id) if workspace_id else Workspace.query.first()
        if not workspace:
            raise click.ClickException("No workspace found")
        agent = db.session.get(Agent, agent_id) if agent_id else Agent.query.first()
        payload = {
            "workspace_id": workspace.id,
            "agent_id": agent.id if agent else None,
            "query": query,
            "top_k": top_k,
            "include_vector_details": True,
            "include_timing": True,
        }
        click.echo(json.dumps(MemoryService().search(payload, semantic=True), indent=2))

    @app.cli.command("benchmark-search")
    @click.argument("query")
    @click.option("--workspace-id", type=int)
    @click.option("--agent-id", type=int)
    @click.option("--queries", default=100, type=int)
    @click.option("--top-k", default=5, type=int)
    def benchmark_search(query, workspace_id, agent_id, queries, top_k):
        workspace = db.session.get(Workspace, workspace_id) if workspace_id else Workspace.query.first()
        if not workspace:
            raise click.ClickException("No workspace found")
        agent = db.session.get(Agent, agent_id) if agent_id else Agent.query.first()
        service = MemoryService()
        service.faiss.warmup(service.embedding_service)
        timings = []
        started = perf_counter()
        for _ in range(queries):
            result = service.search(
                {
                    "workspace_id": workspace.id,
                    "agent_id": agent.id if agent else None,
                    "query": query,
                    "top_k": top_k,
                    "mode": "agent",
                    "compact": True,
                    "include_timing": True,
                    "record_access": False,
                },
                semantic=True,
            )
            timings.append(result["timing"]["total_ms"])
        total_seconds = perf_counter() - started
        ordered = sorted(timings)
        p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
        p99 = ordered[min(len(ordered) - 1, round(0.99 * (len(ordered) - 1)))]
        click.echo(
            json.dumps(
                {
                    "queries": queries,
                    "average_ms": round(sum(timings) / len(timings), 2),
                    "p95_ms": round(p95, 2),
                    "p99_ms": round(p99, 2),
                    "queries_per_second": round(queries / total_seconds, 2) if total_seconds else queries,
                },
                indent=2,
            )
        )

    @app.cli.command("rebuild-correlations")
    @click.option("--workspace-id", type=int)
    def rebuild_correlations(workspace_id):
        workspace_ids = [workspace_id] if workspace_id else [w.id for w in Workspace.query.all()]
        service = CorrelationService()
        for wid in workspace_ids:
            count = service.rebuild_workspace(wid)
            click.echo(json.dumps({"workspace_id": wid, "correlations": count}))

    @app.cli.command("backup")
    @click.option("--output", default="backups")
    def backup(output):
        out = Path(output)
        out.mkdir(parents=True, exist_ok=True)
        db_uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
        stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        if db_uri.startswith("sqlite:///"):
            source = Path(db_uri.removeprefix("sqlite:///"))
            target = out / f"human_brain_{stamp}.sqlite3"
            shutil.copy2(source, target)
            click.echo(str(target))
        else:
            click.echo("For PostgreSQL use: pg_dump $DATABASE_URL > backups/human_brain.sql")

    @app.cli.command("restore")
    @click.argument("backup_path")
    def restore(backup_path):
        db_uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
        if not db_uri.startswith("sqlite:///"):
            click.echo("For PostgreSQL use: psql $DATABASE_URL < backup.sql")
            return
        shutil.copy2(backup_path, Path(db_uri.removeprefix("sqlite:///")))
        click.echo("Restored SQLite backup")

    @app.cli.command("run-worker")
    def run_worker():
        click.echo("Run: celery -A manage.celery worker --loglevel=INFO")

    @app.cli.command("camera-check")
    @click.option("--max-index", default=5, type=int)
    def camera_check(max_index):
        try:
            import cv2
        except Exception as exc:
            click.echo(f"OpenCV unavailable: {exc}")
            return
        for index in range(max_index + 1):
            cap = cv2.VideoCapture(index)
            ok = cap.isOpened()
            if ok:
                width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                click.echo(f"camera {index}: available {int(width)}x{int(height)}")
            else:
                click.echo(f"camera {index}: unavailable")
            cap.release()
