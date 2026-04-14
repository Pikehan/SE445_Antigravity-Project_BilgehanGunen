import os
import glob
import asyncio
import gspread
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google import genai
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from dotenv import load_dotenv

# Load env variables (like GEMINI_API_KEY)
load_dotenv()

if "GEMINI_API_KEY" in os.environ and "GOOGLE_API_KEY" not in os.environ:
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

# Google Sheets OAuth scopes
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Path to the OAuth token (cached after first login)
TOKEN_PATH = os.path.join(os.path.dirname(__file__), "token.json")

# Auto-discover the client_secret_*.json file (name varies by GCP project)
_creds_matches = glob.glob(os.path.join(os.path.dirname(__file__), "client_secret_*.json"))
CREDS_PATH = _creds_matches[0] if _creds_matches else "client_secret.json"

app = FastAPI(title="Player Bug Report Categorizer")

class BugReport(BaseModel):
    player_id: str
    game_version: str
    bug_description: str

def process_bug_report(report: BugReport):
    # 1. Trim whitespace
    report.player_id = report.player_id.strip()
    report.game_version = report.game_version.strip()
    report.bug_description = report.bug_description.strip()
    
    # 2. Validate > 10 chars
    if len(report.bug_description) <= 10:
        raise HTTPException(status_code=400, detail="bug_description must be longer than 10 characters.")
    
    # 3. Generate ISO timestamp
    timestamp = datetime.now(timezone.utc).isoformat()
    return report, timestamp

async def summarize_with_gemini(description: str) -> str:
    # Requires google-genai package
    client = genai.Client()  # Assumes GEMINI_API_KEY is in env
    
    system_prompt = "Act as a Lead QA Tester. Summarize this player bug report into a professional, exactly 10-word technical summary."
    
    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=description,
        config=genai.types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.2,
        )
    )
    return response.text.strip()

def _get_gspread_client() -> gspread.Client:
    """Authenticate with Google and return a gspread client.
    On the first run, a browser window will open for OAuth login.
    After that, the token is cached in token.json.
    """
    creds = None

    # Load cached token if it exists
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # If no valid credentials, perform OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_PATH):
                raise FileNotFoundError(
                    f"Google OAuth credentials file not found at: {CREDS_PATH}\n"
                    "Please download it from Google Cloud Console → APIs & Services → Credentials → "
                    "OAuth 2.0 Client IDs → Download JSON, and save it as 'credentials.json' in the project folder."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the credentials for next run
        with open(TOKEN_PATH, "w") as token_file:
            token_file.write(creds.to_json())

    return gspread.authorize(creds)

async def actuate_to_google_sheets(timestamp: str, player_id: str, version: str, raw_desc: str, summary: str):
    """
    External API (Actuation) Node:
    Connects to Google Sheets via the Sheets API and appends the bug report row.
    If the spreadsheet 'SE445_Bug_Reports' does not exist, it is created automatically.
    """
    # Run the blocking gspread calls in a thread so we don't block the async event loop
    def _write_to_sheet():
        gc = _get_gspread_client()

        # Try to open the sheet; create it if it doesn't exist
        try:
            sheet = gc.open("SE445_Bug_Reports").sheet1
        except gspread.exceptions.SpreadsheetNotFound:
            spreadsheet = gc.create("SE445_Bug_Reports")
            sheet = spreadsheet.sheet1
            # Add header row
            sheet.append_row(["Timestamp", "Player ID", "Version", "Raw Description", "AI Summary"])

        # Append the bug report row
        sheet.append_row([timestamp, player_id, version, raw_desc, summary])
        return f"Row appended to 'SE445_Bug_Reports' spreadsheet."

    result = await asyncio.to_thread(_write_to_sheet)
    return result

@app.post("/webhook/bug-report")
async def handle_bug_report(report: BugReport):
    try:
        # Step 1: Processing Node
        processed_report, timestamp = process_bug_report(report)
        
        # Step 2: AI Completion Node (Gemini)
        summary = await summarize_with_gemini(processed_report.bug_description)
        
        # Step 3: External API / Actuation Node (Google Sheets via gspread)
        sheets_result = await actuate_to_google_sheets(
            timestamp=timestamp,
            player_id=processed_report.player_id,
            version=processed_report.game_version,
            raw_desc=processed_report.bug_description,
            summary=summary
        )
        
        return {
            "status": "success",
            "timestamp": timestamp,
            "summary": summary,
            "sheets_result": sheets_result
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8080)
