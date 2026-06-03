import subprocess
import os
import logging
from pathlib import Path
import threading

log = logging.getLogger(__name__)

def ingest_semantic_event_bg(text: str, category: str = "knowledge"):
    """
    Ingest a semantic event to Angati L1 cache in a background thread.
    Non-blocking, zero-latency to the caller.
    """
    def run_ingest():
        try:
            # Resolve project root and angati.exe path
            project_root = Path(__file__).resolve().parent.parent.parent
            angati_exe = project_root / "angati.exe"
            
            # Setup environment to isolate the database
            env = os.environ.copy()
            env["ANGATI_AGENTS_ROOT"] = str(project_root)
            
            # Spawn process to ingest
            run_fallback = False
            try:
                res = subprocess.run(
                    [str(angati_exe), "memory", "ingest", "--text", text, "--category", category],
                    cwd=str(project_root),
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    check=False
                )
                if res.returncode == 0:
                    log.info(f"[Semantic Ingestion] Successfully ingested event ({category}): {text[:100]}...")
                else:
                    log.warning(f"[Semantic Ingestion] Ingest command failed with code {res.returncode}: {res.stderr.strip()}")
                    run_fallback = True
            except (PermissionError, FileNotFoundError, OSError) as exec_err:
                log.info(f"[Semantic Ingestion] Executing angati.exe failed ({exec_err}). Using direct SQLite fallback.")
                run_fallback = True

            if run_fallback:
                try:
                    import sqlite3
                    import json
                    import time
                    import uuid
                    
                    db_dir = project_root / "memory"
                    db_dir.mkdir(parents=True, exist_ok=True)
                    db_path = db_dir / "V3_brain.db"
                    
                    conn = sqlite3.connect(str(db_path), timeout=10)
                    cursor = conn.cursor()
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS memories (
                            id TEXT PRIMARY KEY,
                            content TEXT,
                            metadata TEXT,
                            summary TEXT,
                            timestamp REAL
                        )
                    """)
                    mem_id = str(uuid.uuid4())
                    metadata_json = json.dumps({"category": category, "source": "fallback_ingest"})
                    cursor.execute(
                        "INSERT INTO memories (id, content, metadata, summary, timestamp) VALUES (?, ?, ?, ?, ?)",
                        (mem_id, text, metadata_json, text, time.time())
                    )
                    conn.commit()
                    conn.close()
                    log.info(f"[Semantic Ingestion] Fallback SQLite successfully ingested event ({category}): {text[:100]}...")
                except Exception as db_err:
                    log.error(f"[Semantic Ingestion] Fallback SQLite ingestion failed: {db_err}")
        except Exception as e:
            log.warning(f"[Semantic Ingestion] Background ingestion error: {e}")

    threading.Thread(target=run_ingest, daemon=True).start()

