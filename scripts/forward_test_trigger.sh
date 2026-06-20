#!/bin/bash
# Script gửi tín hiệu giả lập Forward Test tự động từ Server A

# Đường dẫn tới thư mục VBS để đọc .env
VBS_DIR="/opt/trading-bot/vbs"
ENV_FILE="$VBS_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    source "$ENV_FILE"
fi

SECRET=${WEBHOOK_SECRET:-"change_me_in_dotenv"}
URL="http://localhost:5000/ingest"

# Chọn ngẫu nhiên asset và action
ASSETS=("BTCUSDT" "ETHUSDT" "SOLUSDT")
ACTIONS=("buy" "sell")
SYMBOL=${ASSETS[$RANDOM % ${#ASSETS[@]}]}
ACTION=${ACTIONS[$RANDOM % ${#ACTIONS[@]}]}

# Lấy giá thực tế từ Binance API
PRICE=$(curl -s "https://api.binance.com/api/v3/ticker/price?symbol=$SYMBOL" | grep -oP '"price":"\K[^"]+')

if [ -z "$PRICE" ]; then
    PRICE="60000.00" # Fallback price
fi

# Đóng gói JSON Payload
PAYLOAD=$(cat <<EOF
{
  "secret": "$SECRET",
  "action": "$ACTION",
  "symbol": "$SYMBOL",
  "price": "$PRICE",
  "quoteQty": 50,
  "interval": "60",
  "mode": "FORWARD",
  "source": "simulation_cron"
}
EOF
)

# Gửi tín hiệu tới VBS
curl -s -X POST -H "Content-Type: application/json" -d "$PAYLOAD" "$URL"
