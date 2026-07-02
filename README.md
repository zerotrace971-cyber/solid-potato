Pritam bro tui jodi dekhchish then ektu clone korish repo and windows er part ta test korish

clone it
then terminal e ja
.\install_service_windows.ps1

Get-Service argus-auth, argus-system 

use these command on powershell bruh...jodi na paarish use ai🫱🫲

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

