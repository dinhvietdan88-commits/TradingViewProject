import asyncio
import time
import os
import sys
from httpx import AsyncClient, ASGITransport

# Add 'server' path to sys.path so we can import modules directly
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
)

import config
import database
from main import app, limiter

limiter.enabled = False


async def run_stress_test(num_requests=280):
    print("=== STARTING WEBHOOK STRESS TEST ===")
    print(f"Target: {num_requests} concurrent signals")

    # 1. Setup config for testing
    config.DISABLE_RATE_LIMIT = True
    config.DB_TIMEOUT = 60.0
    config.TELEGRAM_BOT_ENABLED = False
    config.BRIEF_ENABLED = False
    config.MCP_ENABLED = False
    config.RAG_ENABLED = False
    config.WEBHOOK_SECRET = "stress-test-secret"  # noqa: S105 # pragma: allowlist secret

    # Use a separate test database to avoid polluting live database
    original_db_path = config.DB_PATH
    config.DB_PATH = "stress_test_trades.db"

    # Cleanup any old test DB
    if os.path.exists(config.DB_PATH):
        try:
            os.remove(config.DB_PATH)
        except Exception as e:
            print(f"Warning: could not remove old test DB: {e}")

    try:
        # 2. Re-initialize test database with WAL mode enabled
        await database.init_db()

        # 3. Create httpx ASGI client
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Prepare payloads
            payloads = []
            for i in range(num_requests):
                payloads.append(
                    {
                        "action": "buy" if i % 2 == 0 else "sell",
                        "symbol": f"BTCUSDT_{i}",
                        "price": 60000.0 + i,
                        "quoteQty": 100.0 + i,
                        "secret": "stress-test-secret",  # pragma: allowlist secret
                        "vbs_queue_id": i + 1000,  # unique queue ID
                    }
                )

            # 4. Fire all requests concurrently
            start_time = time.perf_counter()

            tasks = [client.post("/webhook", json=payload) for payload in payloads]

            print(f"Firing {num_requests} requests concurrently...")
            results = await asyncio.gather(*tasks, return_exceptions=True)

            end_time = time.perf_counter()
            duration = end_time - start_time

            # 5. Analyze results
            success_count = 0
            error_count = 0
            status_codes = {}
            exceptions = []

            for res in results:
                if isinstance(res, Exception):
                    error_count += 1
                    exceptions.append(res)
                else:
                    status_codes[res.status_code] = (
                        status_codes.get(res.status_code, 0) + 1
                    )
                    if res.status_code == 200:
                        success_count += 1
                    else:
                        error_count += 1

            print("\n=== RESULTS ===")
            print(f"Total duration: {duration:.4f} seconds")
            print(f"Average latency: {(duration / num_requests) * 1000:.2f} ms")
            print(f"Throughput (RPS): {num_requests / duration:.2f} req/sec")
            print(f"Success count (HTTP 200): {success_count}")
            print(f"Error count: {error_count}")
            print(f"Status codes breakdown: {status_codes}")

            if exceptions:
                print(f"Exceptions encountered: {exceptions[:5]}")

            # 6. Verify database integrity
            db_counts = await database.get_db_counts()
            print("Database verification:")
            print(f"  - Total signals stored: {db_counts.get('signals_count', 0)}")
            print(f"  - Total trades stored: {db_counts.get('trades_count', 0)}")

            # Asset validation
            assert success_count == num_requests, (
                f"Expected {num_requests} successes, got {success_count}"
            )
            assert db_counts.get("signals_count", 0) == num_requests, (
                f"Expected {num_requests} signals in database, got {db_counts.get('signals_count', 0)}"
            )
            print(
                "\n✅ Verification SUCCESS: 280 concurrent signals ingested and stored cleanly without lock errors!"
            )

    finally:
        # Restore database setting and cleanup test DB file
        config.DB_PATH = original_db_path
        if os.path.exists("stress_test_trades.db"):
            await asyncio.sleep(0.5)  # allow connection pool to fully close
            try:
                os.remove("stress_test_trades.db")
                print("Cleaned up stress test database file.")
            except Exception as e:
                print(f"Cleanup warning: {e}")


if __name__ == "__main__":
    asyncio.run(run_stress_test(280))
