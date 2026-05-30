import pytest

from app import create_app
from app.extensions import db
from app.models import Agent, ApiKey, User, Workspace, WorkspaceAgent


@pytest.fixture()
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        user = User(email="admin@example.com", name="Admin", role="admin")
        user.set_password("password")
        workspace = Workspace(name="Test")
        agent = Agent(name="Agent")
        db.session.add_all([user, workspace, agent])
        db.session.flush()
        db.session.add(WorkspaceAgent(workspace_id=workspace.id, agent_id=agent.id, permissions={"memory": "rw"}))
        raw, prefix, key_hash = ApiKey.create_token()
        db.session.add(ApiKey(agent_id=agent.id, name="test", prefix=prefix, key_hash=key_hash))
        db.session.commit()
        app.config["TEST_API_KEY"] = raw
        app.config["TEST_AGENT_ID"] = agent.id
        app.config["TEST_WORKSPACE_ID"] = workspace.id
        db.session.expunge_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def api_headers(app):
    return {"X-API-Key": app.config["TEST_API_KEY"]}
