#!/usr/bin/env python3
"""FastAPI backend for ARGUS SOC analysis and the deception grid."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent
AI_ROOT = ROOT.parent
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

PROJECT_ROOT = AI_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from honeypot import HoneypotRuntime, HoneypotSettings, TelemetryStore  # noqa: E402


DASHBOARD_ROOT = PROJECT_ROOT / "dashboard"


class LogEventRequest(BaseModel):
    event: Dict[str, Any]
    brute_force_detected: bool = False


class BatchLogEventRequest(BaseModel):
    events: List[Dict[str, Any]] = Field(default_factory=list)
    brute_force_detected: bool = False


class RagQueryRequest(BaseModel):
    query: str
    session_id: str = "api"
    top_k: int = Field(default=5, ge=1, le=10)


class BlockSourceRequest(BaseModel):
    source_ip: str = Field(min_length=1, max_length=128)


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def create_app(
    use_rag: bool = True,
    use_llm: bool = True,
    *,
    honeypot_store: Optional[TelemetryStore] = None,
    honeypot_runtime: Optional[HoneypotRuntime] = None,
    honeypot_autostart: Optional[bool] = None,
) -> FastAPI:
    settings = HoneypotSettings.from_env()
    store = honeypot_store or (
        honeypot_runtime.store
        if honeypot_runtime is not None
        else TelemetryStore(settings.database_path)
    )
    runtime = honeypot_runtime or HoneypotRuntime(settings=settings, store=store)
    should_autostart = settings.autostart if honeypot_autostart is None else honeypot_autostart

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if should_autostart:
            await runtime.start()
        yield
        await runtime.stop()

    app = FastAPI(title="ARGUS API", version="1.0.0", lifespan=lifespan)
    app.state.use_rag = use_rag
    app.state.use_llm = use_llm
    app.state.orchestrator = None
    app.state.rag_pipeline = None
    app.state.honeypot_store = store
    app.state.honeypot_runtime = runtime

    def get_orchestrator() -> Any:
        if app.state.orchestrator is None:
            from orchestrator import Orchestrator

            app.state.orchestrator = Orchestrator(use_rag=use_rag, use_llm=use_llm)
        return app.state.orchestrator

    def get_rag_pipeline() -> Any:
        if app.state.rag_pipeline is None:
            from rag.core.pipeline import RAGPipeline

            app.state.rag_pipeline = RAGPipeline(enable_retrieval=use_rag, enable_llm=use_llm)
        return app.state.rag_pipeline

    @app.get("/health")
    def health() -> Dict[str, Any]:
        rag_pipeline = app.state.rag_pipeline
        return {
            "status": "ok",
            "service": "argus-api",
            "configured": {
                "use_rag": app.state.use_rag,
                "use_llm": app.state.use_llm,
            },
            "initialized": {
                "orchestrator": app.state.orchestrator is not None,
                "rag_pipeline": rag_pipeline is not None,
            },
            "rag_enabled": rag_pipeline.retriever is not None if rag_pipeline else False,
            "llm_enabled": rag_pipeline.llm is not None if rag_pipeline else False,
            "memory_backend": rag_pipeline.memory.backend if rag_pipeline else "uninitialized",
            "honeypot": runtime.status(),
        }

    @app.get("/", include_in_schema=False)
    def root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/dashboard")

    @app.get("/dashboard", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(DASHBOARD_ROOT / "index.html", media_type="text/html")

    @app.get("/dashboard/styles.css", include_in_schema=False)
    def dashboard_styles() -> FileResponse:
        return FileResponse(DASHBOARD_ROOT / "styles.css", media_type="text/css")

    @app.get("/dashboard/app.js", include_in_schema=False)
    def dashboard_script() -> FileResponse:
        return FileResponse(
            DASHBOARD_ROOT / "app.js", media_type="application/javascript"
        )

    @app.post("/api/v1/logs")
    def ingest_log(request: LogEventRequest) -> Dict[str, Any]:
        try:
            result = get_orchestrator().investigate(
                request.event,
                brute_force_detected=request.brute_force_detected,
            )
            return result.to_dict()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/v1/logs/batch")
    def ingest_logs(request: BatchLogEventRequest) -> Dict[str, Any]:
        results = []
        errors = []
        orchestrator = get_orchestrator()
        for index, event in enumerate(request.events):
            try:
                result = orchestrator.investigate(
                    event,
                    brute_force_detected=request.brute_force_detected,
                )
                results.append(result.to_dict())
            except Exception as exc:
                errors.append(
                    {"index": index, "error": str(exc), "event_id": event.get("event_id")}
                )
        return {
            "processed": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors,
        }

    @app.post("/api/v1/rag/query")
    def rag_query(request: RagQueryRequest) -> Dict[str, Any]:
        try:
            return get_rag_pipeline().answer_query(
                query=request.query,
                session_id=request.session_id,
                top_k=request.top_k,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/v1/honeypot/status")
    def honeypot_status() -> Dict[str, Any]:
        return runtime.status()

    @app.post("/api/v1/honeypot/control/start")
    async def honeypot_start() -> Dict[str, Any]:
        return await runtime.start()

    @app.post("/api/v1/honeypot/control/stop")
    async def honeypot_stop() -> Dict[str, Any]:
        return await runtime.stop()

    @app.get("/api/v1/honeypot/metrics")
    def honeypot_metrics() -> Dict[str, Any]:
        return store.metrics()

    @app.get("/api/v1/honeypot/sessions")
    def honeypot_sessions(
        limit: int = Query(default=100, ge=1, le=500),
        status: Optional[str] = Query(default=None, max_length=32),
    ) -> Dict[str, Any]:
        sessions = store.list_sessions(limit=limit, status=status)
        return {"count": len(sessions), "sessions": sessions}

    @app.get("/api/v1/honeypot/sessions/{session_id}")
    def honeypot_session(session_id: str) -> Dict[str, Any]:
        session = store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return {
            "session": session,
            "events": list(
                reversed(store.list_events(session_id=session_id, limit=500))
            ),
        }

    @app.post("/api/v1/honeypot/sessions/{session_id}/contain")
    async def contain_honeypot_session(session_id: str) -> Dict[str, Any]:
        if not await runtime.contain(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        return {"ok": True, "session_id": session_id, "status": "contained"}

    @app.post("/api/v1/honeypot/block-source")
    async def block_honeypot_source(request: BlockSourceRequest) -> Dict[str, Any]:
        contained = await runtime.block_source(request.source_ip)
        return {
            "ok": True,
            "source_ip": request.source_ip,
            "contained_sessions": contained,
            "scope": "ARGUS runtime blocklist",
        }

    @app.get("/api/v1/honeypot/events")
    def honeypot_events(
        session_id: Optional[str] = Query(default=None, max_length=80),
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> Dict[str, Any]:
        events = store.list_events(session_id=session_id, limit=limit)
        return {"count": len(events), "events": events}

    @app.get("/api/v1/honeypot/sessions/{session_id}/export")
    def export_honeypot_session(session_id: str) -> JSONResponse:
        evidence = store.export_session(session_id)
        if evidence is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return JSONResponse(
            content=evidence,
            headers={
                "Content-Disposition": f'attachment; filename="argus-{session_id}.json"'
            },
        )

    return app


app = create_app(
    use_rag=_env_flag("API_USE_RAG", True),
    use_llm=_env_flag("API_USE_LLM", True),
)
