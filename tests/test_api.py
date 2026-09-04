from dataclasses import replace

from fastapi.testclient import TestClient

from Ai.backend.api_server import create_app
from honeypot.config import HoneypotSettings, default_services
from honeypot.runtime import HoneypotRuntime
from honeypot.store import TelemetryStore


def test_dashboard_and_honeypot_api(tmp_path):
    settings = HoneypotSettings(
        bind_host="127.0.0.1",
        database_path=tmp_path / "api.db",
        certificate_dir=tmp_path / "certs",
        enable_gemini=False,
        services=tuple(replace(item, port=0) for item in default_services()),
    )
    store = TelemetryStore(settings.database_path)
    runtime = HoneypotRuntime(settings=settings, store=store)
    app = create_app(
        use_rag=False,
        use_llm=False,
        honeypot_store=store,
        honeypot_runtime=runtime,
        honeypot_autostart=False,
    )

    with TestClient(app) as client:
        dashboard = client.get("/dashboard")
        assert dashboard.status_code == 200
        assert "ARGUS" in dashboard.text
        assert client.get("/api/v1/honeypot/status").json()["running"] is False
        started = client.post("/api/v1/honeypot/control/start")
        assert started.status_code == 200
        assert len(started.json()["services"]) == 5
        metrics = client.get("/api/v1/honeypot/metrics")
        assert metrics.status_code == 200
        stopped = client.post("/api/v1/honeypot/control/stop")
        assert stopped.status_code == 200
        assert stopped.json()["running"] is False

    store.close()
