# SE445 HW1 – Player Bug Report Categorizer
**Bilgehan Günen | SE 445 Prompt Engineering**

## Overview
A FastAPI webhook pipeline that receives player bug reports, validates and processes them, generates a professional AI summary using the Gemini API, and appends the results to a Google Sheet.


## Files
| File | Purpose |
|------|---------|
| `server.py` | Main application — all 4 pipeline nodes implemented |
| `test_request.py` | Automated integration tests (7 test cases) |
| `workflow.json` | Workflow architecture definition |
| `requirements.txt` | Python runtime dependencies |
| `.env` *(not committed)* | `GEMINI_API_KEY=your_key_here` |
| `token.json` *(not committed)* | Cached Google OAuth token (auto-generated on first run) |
| `client_secret_*.json` *(not committed)* | Google OAuth credentials (download from GCP Console) |

## Setup

### 1. Create and activate virtual environment
```bash
python -m venv .venv
.venv\Scripts\activate
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure environment variables
Create a `.env` file in this directory:
```
GEMINI_API_KEY=your_gemini_api_key_here
```

### 4. Google Sheets OAuth setup
1. Go to [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials
2. Create an OAuth 2.0 Client ID (Desktop App) and download the JSON file
3. Place the downloaded file in this folder — it will be named `client_secret_*.json`
   - `server.py` **auto-discovers** any file matching that pattern, no manual edits needed
4. On first run, a browser window opens for Google login — after that `token.json` is cached automatically

## Running

### Start the server
```bash
python server.py
```
Server starts at: `http://127.0.0.1:8080`

### Run automated tests
```bash
python test_request.py
```

### Manual test (curl)
```bash
curl -X POST http://127.0.0.1:8080/webhook/bug-report \
  -H "Content-Type: application/json" \
  -d "{\"player_id\": \"P-4921\", \"game_version\": \"v1.2.4\", \"bug_description\": \"When I try to jump on the main platform while holding the red key, the item disappears and my character gets stuck.\"}"
```

### Interactive API docs (Swagger UI)
Visit: [http://127.0.0.1:8080/docs](http://127.0.0.1:8080/docs)

## Endpoint

### `POST /webhook/bug-report`

**Request body:**
```json
{
  "player_id": "P-4921",
  "game_version": "v1.2.4",
  "bug_description": "Detailed description of the bug (must be > 10 characters)"
}
```

**Success response (200):**
```json
{
  "status": "success",
  "timestamp": "2026-04-14T00:00:00+00:00",
  "summary": "AI-generated 10-word technical summary of the bug",
  "sheets_result": "Row appended to 'SE445_Bug_Reports' spreadsheet."
}
```

**Validation error (400):** Returned when `bug_description` is ≤ 10 characters.  
**Schema error (422):** Returned when required fields are missing.

