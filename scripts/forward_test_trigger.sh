#!/bin/bash

# ==============================================================================
# FORWARD TEST TRIGGER SCRIPT (BASH)
# Server A -> Server C (Local) VBS Ingress Simulator
# ==============================================================================

# Cấu hình mặc định
URL="http://localhost:5000/webhook" # Endpoint VBS chạy trên Server A
SYMBOL="SOLUSDT"                    # Chọn SOLUSDT vì thanh khoản cao, biến động rõ ràng
INTERVAL="60"
ENV_FILE="/opt/trading-bot/vbs/.env"
SECRET="change_me_in_dotenv"

# Lấy Secret từ file .env nếu có
if [ -f "$ENV_FILE" ]; then
    SECRET_FROM_ENV=$(grep "^BUFFER_SECRET=" "$ENV_FILE" | cut -d '=' -f 2)
    # Tương thích nếu dùng WEBHOOK_SECRET thay vì BUFFER_SECRET
    if [ -z "$SECRET_FROM_ENV" ]; then
        SECRET_FROM_ENV=$(grep "^WEBHOOK_SECRET=" "$ENV_FILE" | cut -d '=' -f 2)
    fi
    if [ -n "$SECRET_FROM_ENV" ]; then
        SECRET="$SECRET_FROM_ENV"
    fi
fi

# ==============================================================================
# LẤY GIÁ TRỊ THỊ TRƯỜNG THỰC TẾ TỪ BINANCE API
# ==============================================================================
PRICE=$(curl -s "https://api.binance.com/api/v3/ticker/price?symbol=${SYMBOL}" | jq -r '.price')
if [ -z "$PRICE" ] || [ "$PRICE" == "null" ]; then
    echo "[-] Không lấy được giá từ Binance API. Sử dụng giá mặc định."
    PRICE="150.00" # Fallback tĩnh
fi

# Randomize Action (Mô phỏng cả thị trường bò và gấu)
ACTIONS=("BUY" "SELL")
RANDOM_INDEX=$((RANDOM % 2))
ACTION=${ACTIONS[$RANDOM_INDEX]}

# Tạo thời gian hiện tại ISO 8601
CURRENT_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ==============================================================================
# XÂY DỰNG JSON PAYLOAD
# ==============================================================================
# THUỘC TÍNH QUAN TRỌNG: "mode": "FORWARD"
PAYLOAD=$(cat <<EOF
{
    "secret": "$SECRET",
    "action": "$ACTION",
    "symbol": "$SYMBOL",
    "price": "$PRICE",
    "quoteQty": 50,
    "interval": "$INTERVAL",
    "time": "$CURRENT_TIME",
    "indicator": "ForwardTest_Simulator",
    "mode": "FORWARD",
    "message": "Automated forward test ping from Server A cronjob"
}
EOF
)

echo "=============================================="
echo -e "\033[1;36mGửi tín hiệu Forward Test giả lập TradingView...\033[0m"
echo -e "\033[1;33mURL:\033[0m $URL"
echo -e "\033[1;33mAction:\033[0m $ACTION | \033[1;33mSymbol:\033[0m $SYMBOL | \033[1;33mPrice:\033[0m $PRICE"
echo -e "\033[1;30mPayload:\033[0m"
echo "$PAYLOAD"
echo "=============================================="

# Gửi HTTP POST
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD")

HTTP_STATUS=$(echo "$RESPONSE" | tail -n 1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [ "$HTTP_STATUS" -eq 200 ]; then
    echo -e "\n\033[1;32m[+] KẾT QUẢ TỪ SERVER (200 OK):\033[0m"
    echo "$BODY"
else
    echo -e "\n\033[1;31m[-] LỖI KHI GỬI WEBHOOK (HTTP $HTTP_STATUS):\033[0m"
    echo "$BODY"
fi
