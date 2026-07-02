#!/usr/bin/env python3
"""Minimal FastAPI backend for ARGUS log ingest and RAG queries."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent
AI_ROOT = ROOT.parent
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from orchestrator import Orchestrator  # noqa: E402
from rag.core.pipeline import RAGPipeline  # noqa: E402


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


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def create_app(use_rag: bool = True, use_llm: bool = True) -> FastAPI:
    app = FastAPI(title="ARGUS API", version="0.1.0")
    app.state.use_rag = use_rag
    app.state.use_llm = use_llm
    app.state.orchestrator = None
    app.state.rag_pipeline = None

    def get_orchestrator() -> Orchestrator:
        if app.state.orchestrator is None:
            app.state.orchestrator = Orchestrator(use_rag=use_rag, use_llm=use_llm)
        return app.state.orchestrator

    def get_rag_pipeline() -> RAGPipeline:
        if app.state.rag_pipeline is None:
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
        }

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

    return app


app = create_app(
    use_rag=_env_flag("API_USE_RAG", True),
    use_llm=_env_flag("API_USE_LLM", True),
)
