import time
import requests
import sys
import os
import threading
import uvicorn

# Force UTF-8 output so emoji and special chars work on Windows
sys.stdout.reconfigure(encoding="utf-8")

# Resolve absolute paths so it works no matter where you run it from
DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(DIR, ".env")

# Create mock .env just in case so load_dotenv doesn't complain
if not os.path.exists(env_path):
    with open(env_path, "w") as f:
        f.write('GEMINI_API_KEY="MOCK_KEY_FOR_TEST"\n')

# Add directory to sys.path so we can import from server.py directly
sys.path.append(DIR)
from server import app  # noqa: E402

PORT = 8080
BASE_URL = f"http://127.0.0.1:{PORT}/webhook/bug-report"

print("Starting server internally (daemon thread)...")
def run_server():
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")

server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()

# Give uvicorn a few seconds to fully bind to the port
time.sleep(3)

try:
    # ---------------------------------------------------------------------------
    # Test cases
    # ---------------------------------------------------------------------------
    test_cases = [
        {
            "name": "✅  VALID   — Normal bug report",
            "payload": {
                "name": "P-4921",
                "email": "test@example.com",
                "message": "[v1.2.4] When I try to jump on the main platform while holding the red key, the specific item disappears and my character gets stuck in the floor."
            },
            "expect_code": 200,
        },
        {
            "name": "✅  VALID   — Whitespace padding (should be trimmed)",
            "payload": {
                "name": "   P-0001   ",
                "email": "  test@example.com  ",
                "message": "   The inventory screen freezes completely when opening it during a multiplayer match.   "
            },
            "expect_code": 200,
        },
        {
            "name": "✅  VALID   — Different game version & player",
            "payload": {
                "name": "P-7777",
                "email": "john.doe@email.com",
                "message": "[v0.9.1-beta] Audio cuts out entirely after respawning in the third dungeon area near the boss room."
            },
            "expect_code": 200,
        },
        {
            "name": "❌  INVALID — message too short (≤10 chars)",
            "payload": {
                "name": "P-0002",
                "email": "test@example.com",
                "message": "crash"
            },
            "expect_code": 400,
        },
        {
            "name": "❌  INVALID — message exactly 10 chars (boundary)",
            "payload": {
                "name": "P-0003",
                "email": "test@example.com",
                "message": "1234567890"
            },
            "expect_code": 400,
        },
        {
            "name": "❌  INVALID — Missing required field (no name)",
            "payload": {
                "email": "test@test.com",
                "message": "Game crashes on startup every time without any error message shown."
            },
            "expect_code": 422,
        },
        {
            "name": "❌  INVALID — Empty message",
            "payload": {
                "name": "P-0004",
                "email": "test@example.com",
                "message": ""
            },
            "expect_code": 400,
        },
        {
            "name": "❌  INVALID — Invalid email format",
            "payload": {
                "name": "P-0005",
                "email": "invalidemail.com",
                "message": "Trying to test the email validation logic with a bad email format."
            },
            "expect_code": 400,
        },
    ]

    # ---------------------------------------------------------------------------
    # Run tests
    # ---------------------------------------------------------------------------
    passed = 0
    failed = 0

    print(f"\nRunning {len(test_cases)} test cases...\n" + "=" * 60)

    for tc in test_cases:
        print(f"\n{tc['name']}")
        print(f"  Payload: {tc['payload']}")
        try:
            # 120s timeout since API calls are much faster than complete UI automation loops
            response = requests.post(BASE_URL, json=tc["payload"], timeout=120)
            code = response.status_code
            try:
                body = response.json()
            except ValueError:
                body = response.text

            if code == tc["expect_code"]:
                print(f"  ✅ PASS  (HTTP {code})")
                if code == 200 and isinstance(body, dict):
                    print(f"     summary      : {body.get('summary')}")
                    print(f"     sheets_result: {body.get('sheets_result')}")
                    print(f"     email_result : {body.get('email_result')}")
                else:
                    print(f"     detail: {body}")
                passed += 1
            else:
                print(f"  ❌ FAIL  (expected HTTP {tc['expect_code']}, got {code})")
                print(f"     body: {body}")
                failed += 1
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            failed += 1

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"Results: {passed}/{len(test_cases)} passed, {failed} failed")

finally:
    print("\nTests completed. Closing terminal will cleanly kill the daemon thread server.")
