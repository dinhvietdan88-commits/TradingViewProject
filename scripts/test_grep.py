import sys

sys.path.append("scripts")
from verify_provisioning import SSHConn

conn_a = SSHConn(
    "Server A", "100.92.13.100", "root", r"C:\Users\pesil\.ssh\pk\sshkey-serverc.pem"
)
print("Grep Telegram:")
print(
    conn_a.run(
        'grep -E "^TELEGRAM_BOT_TOKEN=" /opt/trading-bot/.env /opt/trading-bot/vbs/.env /home/botuser/trading-bot/.env /home/botuser/trading-bot/vbs/.env 2>/dev/null'
    )
)
print("Grep BUFFER_SECRET:")
print(
    conn_a.run(
        'grep -E "^BUFFER_SECRET=" /opt/trading-bot/.env /opt/trading-bot/vbs/.env /home/botuser/trading-bot/.env /home/botuser/trading-bot/vbs/.env 2>/dev/null'
    )
)
