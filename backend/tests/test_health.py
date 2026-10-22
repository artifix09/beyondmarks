"""Smoke tests for the scaffold.

These exist so that `pytest -q` is green from the first commit. Once M7 lands,
the engine tests in this folder are the ones that matter.
"""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app

client = TestClient(app)


def test_health_responds():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_health_reports_missing_env():
    """An unconfigured API says which keys are missing instead of crashing."""
    res = client.get("/health")
    body = res.json()
    assert "missing_env" in body
    assert isinstance(body["missing_env"], list)


def test_settings_lists_every_required_key():
    missing = Settings(_env_file=None).missing()
    assert set(missing) == {
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_JWT_SECRET",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "GEMINI_EMBED_MODEL",
    }


def test_cors_origins_parse():
    settings = Settings(_env_file=None, cors_origins="http://a.test, http://b.test")
    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]
