import sys
from pathlib import Path
import datetime

# Add project root to sys.path so 'auth' and 'config' can be imported
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv()  # Explicitly load .env file

import config
from auth.service import AuthService
from auth.auth_config import AuthConfig
import sqlite3
from datetime import datetime, timezone, timedelta

db_path = config.DB_PATH
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Check if auth_sessions table has any active sessions
cursor.execute("SELECT * FROM auth_sessions ORDER BY created_at DESC LIMIT 1")
row = cursor.fetchone()

if not row:
    print("No active session found in DB. Creating a dummy session...")
    import uuid

    sid = str(uuid.uuid4())
    # Use config's Telegram chat id as the allowed user id
    tid = int(config.TELEGRAM_CHAT_IDS[0]) if config.TELEGRAM_CHAT_IDS else 6210691549
    created_at = datetime.now(timezone.utc).isoformat()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    cursor.execute(
        "INSERT INTO auth_sessions (session_id, telegram_id, username, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (sid, tid, "pesil", created_at, expires_at),
    )
    conn.commit()
    cursor.execute("SELECT * FROM auth_sessions WHERE session_id = ?", (sid,))
    row = cursor.fetchone()

# Parse row into SessionData
from auth.models import SessionData

created_at_dt = datetime.fromisoformat(row["created_at"])
if created_at_dt.tzinfo is None:
    created_at_dt = created_at_dt.replace(tzinfo=timezone.utc)

expires_at_dt = None
if row["expires_at"]:
    expires_at_dt = datetime.fromisoformat(row["expires_at"])
    if expires_at_dt.tzinfo is None:
        expires_at_dt = expires_at_dt.replace(tzinfo=timezone.utc)

session = SessionData(
    session_id=row["session_id"],
    telegram_id=row["telegram_id"],
    username=row["username"],
    created_at=created_at_dt,
    expires_at=expires_at_dt,
    never_expires=False,
)

auth_cfg = AuthConfig()
auth_service = AuthService(auth_cfg)
token = auth_service.create_session_token(session)
print(f"tg_session={token}")
conn.close()
