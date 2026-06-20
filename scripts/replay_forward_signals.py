import json
import os
import re
import time
import requests


def get_webhook_secret():
    try:
        env_path = os.path.join(os.getcwd(), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
                match = re.search(r"^WEBHOOK_SECRET\s*=\s*(.+)$", content, re.MULTILINE)
                if match:
                    return match.group(1).strip()
    except Exception as e:
        print(f"[WARN] Error reading .env file: {e}")
    return "your_webhook_secret_here"


def main():
    print("=== Forward Test Signals Replay Campaign ===")
    print("=======================================")

    secret = get_webhook_secret()

    archive_path = os.path.join(os.getcwd(), "trades", "pattern_archive.json")
    if not os.path.exists(archive_path):
        print(f"[ERROR] Pattern archive file not found at: {archive_path}")
        return

    with open(archive_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    trades = data.get("trades", [])
    print(f"Found {len(trades)} historical trades in archive.")

    # We will replay the first 15 trades as a representative smoke sample
    replay_count = min(15, len(trades))
    print(f"Replaying first {replay_count} trades...")

    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    webhook_url = "http://localhost:5000/webhook"

    success_count = 0

    for i in range(replay_count):
        trade = trades[i]
        symbol = symbols[i % len(symbols)]
        action = "buy" if trade.get("side") == "long" else "sell"
        # Alternate modes to test both MinerviniSepaProcessor (MTT) and MeanReversionProcessor (MIS)
        mode = "MTT" if i % 2 == 0 else "MIS"

        payload = {
            "secret": secret,
            "symbol": symbol,
            "action": action,
            "price": str(trade.get("entry_price")),
            "quoteQty": 100.0,
            "interval": "15",
            "mode": mode,
            "exchange": "binance",
            "sl": str(trade.get("sl")),
            "tp": str(trade.get("tp")),
        }

        try:
            r = requests.post(webhook_url, json=payload, timeout=5)
            status = r.status_code
            try:
                resp_data = r.json()
                outcome = resp_data.get("status", "unknown")
                reason = resp_data.get("reason", "")
            except Exception:
                outcome = "non-json"
                reason = r.text[:50]

            print(
                f"[{i + 1}/{replay_count}] Sent {symbol} {action.upper()} @ {payload['price']} | Status: {status} | Outcome: {outcome} ({reason})"
            )
            if status == 200:
                success_count += 1
        except Exception as e:
            print(f"[{i + 1}/{replay_count}] Error sending {symbol}: {e}")

        time.sleep(0.5)

    print("\n=======================================")
    print(
        f"Replay campaign finished. Successfully sent: {success_count}/{replay_count}"
    )


if __name__ == "__main__":
    main()
