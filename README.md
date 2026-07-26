
## Minimal API backend

Run the FastAPI backend:

```powershell
uvicorn Ai.backend.api_server:app --reload
```

Endpoints:

- `GET /health`
- `POST /api/v1/logs`
- `POST /api/v1/logs/batch`
- `POST /api/v1/rag/query`

