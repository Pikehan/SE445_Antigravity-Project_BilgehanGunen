import os
import glob
import asyncio
import gspread
import traceback
import smtplib
import uvicorn
from email.message import EmailMessage
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
    name: str
    email: str
    message: str

def process_bug_report(report: BugReport):
    # 1. Trim whitespace
    report.name = report.name.strip()
    report.email = report.email.strip()
    report.message = report.message.strip()
    
    # 2. Validate > 10 chars
    if len(report.message) <= 10:
        raise HTTPException(status_code=400, detail="message must be longer than 10 characters.")
    if "@" not in report.email:
        raise HTTPException(status_code=400, detail="Invalid email format.")
    
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

async def actuate_to_google_sheets(timestamp: str, name: str, email: str, message: str, summary: str):
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
            sheet.append_row(["Timestamp", "Name", "Email", "Message", "AI Summary"])

        # Append the bug report row
        sheet.append_row([timestamp, name, email, message, summary])
        return f"Row appended to 'SE445_Bug_Reports' spreadsheet."

    result = await asyncio.to_thread(_write_to_sheet)
    return result

async def send_acknowledgment_email(name: str, email: str):
    """
    Send an email acknowledgment back to the user.
    Uses mock behavior if SMTP credentials are not provided.
    """
    smtp_email = os.environ.get("SMTP_EMAIL")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    
    if not smtp_email or not smtp_password:
        return f"Mock Email sent to {email}: 'We received your ticket'"

    def _send():
        msg = EmailMessage()
        msg.set_content(f"Hi {name},\n\nWe received your ticket and our team will look into it shortly.\n\nBest,\nSupport Team")
        msg["Subject"] = "We received your ticket"
        msg["From"] = smtp_email
        msg["To"] = email

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(smtp_email, smtp_password)
                server.send_message(msg)
            return "Email sent successfully"
        except Exception as e:
            return f"Failed to send email: {e}"

    return await asyncio.to_thread(_send)

@app.post("/webhook/bug-report")
async def handle_bug_report(report: BugReport):
    try:
        # Step 1: Processing Node
        processed_report, timestamp = process_bug_report(report)
        
        # Step 2: AI Completion Node (Gemini)
        summary = await summarize_with_gemini(processed_report.message)
        
        # Step 3: External API / Actuation Node (Google Sheets via gspread)
        sheets_result = await actuate_to_google_sheets(
            timestamp=timestamp,
            name=processed_report.name,
            email=processed_report.email,
            message=processed_report.message,
            summary=summary
        )
        
        # Step 4: Email functionality
        email_result = await send_acknowledgment_email(processed_report.name, processed_report.email)
        
        return {
            "status": "success",
            "timestamp": timestamp,
            "summary": summary,
            "sheets_result": sheets_result,
            "email_result": email_result
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=8080)
