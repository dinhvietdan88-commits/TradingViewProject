import os
import sys
import time
import sqlite3
import requests
import unittest
import threading
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Reconfigure stdout/stderr encoding to prevent Windows cp1252 errors
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="ignore")

# Add nerves/core to sys.path
CORE_PATH = PROJECT_ROOT / "nerves" / "core"
if str(CORE_PATH) not in sys.path:
    sys.path.insert(0, str(CORE_PATH))

import hook_service  # noqa: E402
from ingest_helper import ingest_semantic_event_bg  # noqa: E402


class TestAngatiIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Configure env variables for testing isolation
        os.environ["ANGATI_AGENTS_ROOT"] = str(PROJECT_ROOT)
        os.environ["ANGATI_BUS_BIND"] = (
            "127.0.0.1:9109"  # Use a different port for testing
        )

        # Start local SRA Server on test port in a background thread
        cls.port = 9109
        cls.server_address = ("127.0.0.1", cls.port)

        # Set AGENTS_ROOT in hook_service to test isolation
        hook_service.AGENTS_ROOT = PROJECT_ROOT
        if hasattr(hook_service, "scar_memory") and hook_service.scar_memory:
            hook_service.scar_memory.AGENTS_ROOT = PROJECT_ROOT

        cls.httpd = hook_service.ThreadingHTTPServer(
            cls.server_address, hook_service.SRAHookHandler
        )
        cls.server_thread = threading.Thread(
            target=cls.httpd.serve_forever, daemon=True
        )
        cls.server_thread.start()

        # Give the server a moment to start
        time.sleep(1.0)

    @classmethod
    def tearDownClass(cls):
        # Shutdown the server
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.server_thread.join()

    def test_sra_health_endpoint(self):
        """Verify SRA Server health endpoint returns 200 OK."""
        url = f"http://127.0.0.1:{self.port}/health"
        try:
            response = requests.get(url, timeout=2.0)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "healthy"})
            print("[OK] Test 1: SRA Server Health Endpoint passed!")
        except Exception as e:
            self.fail(f"Failed to connect to SRA Server health endpoint: {e}")

    def test_event_ingestion(self):
        """Verify background semantic event ingestion writes to local database."""
        test_message = f"Test Integration Event - {int(time.time())}"

        # Clear/initialize test db file
        db_path = PROJECT_ROOT / "memory" / "V3_brain.db"

        # Call ingestion helper
        print(f"Ingesting: '{test_message}'")
        ingest_semantic_event_bg(test_message, category="test_run")

        # Poll database to see if record is written
        found = False
        start_time = time.time()

        while time.time() - start_time < 5.0:  # 5 seconds timeout
            time.sleep(0.5)
            if db_path.exists():
                try:
                    conn = sqlite3.connect(str(db_path))
                    cursor = conn.cursor()

                    # Read table structures to find where memory is stored
                    # The V3 memory schema has a table named 'memories' or 'l1_cache'
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    tables = [row[0] for row in cursor.fetchall()]

                    for table in tables:
                        try:
                            if table not in [
                                "memories",
                                "l1_cache",
                                "entities",
                                "relations",
                                "observations",
                            ]:
                                continue

                            if table == "memories":
                                cursor.execute("SELECT * FROM memories")
                            elif table == "l1_cache":
                                cursor.execute("SELECT * FROM l1_cache")
                            elif table == "entities":
                                cursor.execute("SELECT * FROM entities")
                            elif table == "relations":
                                cursor.execute("SELECT * FROM relations")
                            elif table == "observations":
                                cursor.execute("SELECT * FROM observations")
                            else:
                                continue

                            rows = cursor.fetchall()
                            for row in rows:
                                row_str = str(row)
                                if test_message in row_str:
                                    found = True
                                    print(
                                        f"[OK] Ingestion verified in table '{table}': {row}"
                                    )
                                    break
                        except ValueError as e:
                            import logging

                            logging.getLogger(__name__).warning("Ignored: %s", e)
                        if found:
                            break
                    conn.close()
                except Exception as db_err:
                    print(f"Waiting for DB lock/file: {db_err}")
            if found:
                break

        self.assertTrue(
            found, "Test message was not found in the local memory database."
        )
        print("[OK] Test 2: Background Semantic Ingestion verified!")

    def test_angati_version_mismatch_warning(self):
        """Tests that a mismatch triggers the stderr warning (using environment overrides)."""
        import tempfile
        import os
        from contextlib import redirect_stderr
        from io import StringIO

        f1 = tempfile.NamedTemporaryFile(delete=False)
        f2 = tempfile.NamedTemporaryFile(delete=False)
        try:
            f1.write(b"local_version_data")
            f1.close()
            f2.write(b"brain_version_data")
            f2.close()

            os.environ["ANGATI_LOCAL_EXE_PATH"] = f1.name
            os.environ["ANGATI_BRAIN_EXE_PATH"] = f2.name

            f = StringIO()
            with redirect_stderr(f):
                t = hook_service.check_angati_version_async()
                if t:
                    t.join()

            output = f.getvalue()
            self.assertIn(
                "WARNING: Local angati.exe version mismatch detected!", output
            )
        finally:
            os.environ.pop("ANGATI_LOCAL_EXE_PATH", None)
            os.environ.pop("ANGATI_BRAIN_EXE_PATH", None)
            for temp_f in (f1, f2):
                try:
                    if os.path.exists(temp_f.name):
                        os.unlink(temp_f.name)
                except ValueError as e:
                    import logging

                    logging.getLogger(__name__).warning("Ignored: %s", e)

    def test_angati_version_matching(self):
        """Tests that identical file hashes trigger no warning."""
        import tempfile
        import os
        from contextlib import redirect_stderr
        from io import StringIO

        f1 = tempfile.NamedTemporaryFile(delete=False)
        f2 = tempfile.NamedTemporaryFile(delete=False)
        try:
            content = b"matching_version_data"
            f1.write(content)
            f1.close()
            f2.write(content)
            f2.close()

            os.environ["ANGATI_LOCAL_EXE_PATH"] = f1.name
            os.environ["ANGATI_BRAIN_EXE_PATH"] = f2.name

            f = StringIO()
            with redirect_stderr(f):
                t = hook_service.check_angati_version_async()
                if t:
                    t.join()

            output = f.getvalue()
            self.assertNotIn(
                "WARNING: Local angati.exe version mismatch detected!", output
            )
        finally:
            os.environ.pop("ANGATI_LOCAL_EXE_PATH", None)
            os.environ.pop("ANGATI_BRAIN_EXE_PATH", None)
            for temp_f in (f1, f2):
                try:
                    if os.path.exists(temp_f.name):
                        os.unlink(temp_f.name)
                except ValueError as e:
                    import logging

                    logging.getLogger(__name__).warning("Ignored: %s", e)

    def test_angati_version_missing_files(self):
        """Tests that missing file conditions are handled gracefully and silently."""
        import tempfile
        import os
        from contextlib import redirect_stderr
        from io import StringIO

        # Both missing
        os.environ["ANGATI_LOCAL_EXE_PATH"] = "non_existent_file_local.exe"
        os.environ["ANGATI_BRAIN_EXE_PATH"] = "non_existent_file_brain.exe"
        try:
            f = StringIO()
            with redirect_stderr(f):
                t = hook_service.check_angati_version_async()
                if t:
                    t.join()
            self.assertEqual(f.getvalue(), "")
        finally:
            os.environ.pop("ANGATI_LOCAL_EXE_PATH", None)
            os.environ.pop("ANGATI_BRAIN_EXE_PATH", None)

        # One missing, one exists
        f1 = tempfile.NamedTemporaryFile(delete=False)
        try:
            f1.write(b"local_version_data")
            f1.close()
            os.environ["ANGATI_LOCAL_EXE_PATH"] = f1.name
            os.environ["ANGATI_BRAIN_EXE_PATH"] = "non_existent_file_brain.exe"

            f = StringIO()
            with redirect_stderr(f):
                t = hook_service.check_angati_version_async()
                if t:
                    t.join()
            self.assertEqual(f.getvalue(), "")
        finally:
            os.environ.pop("ANGATI_LOCAL_EXE_PATH", None)
            os.environ.pop("ANGATI_BRAIN_EXE_PATH", None)
            try:
                if os.path.exists(f1.name):
                    os.unlink(f1.name)
            except ValueError as e:
                import logging

                logging.getLogger(__name__).warning("Ignored: %s", e)


if __name__ == "__main__":
    unittest.main()
