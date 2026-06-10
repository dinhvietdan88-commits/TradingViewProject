# Deployment Runbook: GlitchTip Observability Platform

Tài liệu này hướng dẫn từng bước cài đặt và vận hành dịch vụ **GlitchTip** trên **Monitor VPS** hiện có của EAIS bằng Docker Compose và Nginx Reverse Proxy.

---

## 1. File Cấu hình Docker Compose (`docker-compose.yml`)

Tạo thư mục `/opt/glitchtip` trên Monitor VPS và lưu trữ file `docker-compose.yml` sau đây:

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    container_name: glitchtip-postgres
    volumes:
      - pg-data:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=glitchtip
      - POSTGRES_USER=glitchtip
      - POSTGRES_PASSWORD=secure_postgres_password_change_me
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U glitchtip"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: glitchtip-redis
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  web:
    image: glitchtip/glitchtip:v4.0
    container_name: glitchtip-web
    ports:
      - "8080:8000"
    environment:
      - DATABASE_URL=postgres://glitchtip:secure_postgres_password_change_me@postgres:5432/glitchtip
      - REDIS_URL=redis://redis:6379/0
      - SECRET_KEY=generate_a_long_random_secret_string_here
      - PORT=8000
      - GLITCHTIP_MAX_EVENT_LIFE_DAYS=30 # Giới hạn lưu log 30 ngày để tối ưu ổ đĩa
      - ENABLE_REGISTRATION=False # Khóa đăng ký tự do sau khi tạo tài khoản
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  worker:
    image: glitchtip/glitchtip:v4.0
    container_name: glitchtip-worker
    command: ./bin/run-celery-worker.sh
    environment:
      - DATABASE_URL=postgres://glitchtip:secure_postgres_password_change_me@postgres:5432/glitchtip
      - REDIS_URL=redis://redis:6379/0
      - SECRET_KEY=generate_a_long_random_secret_string_here
      - GLITCHTIP_MAX_EVENT_LIFE_DAYS=30
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

volumes:
  pg-data:
```

---

## 2. Các Bước Khởi Tạo

1. **Khởi chạy các service:**
   ```bash
   docker compose up -d
   ```
2. **Khởi chạy database migration và tạo tài khoản quản trị:**
   ```bash
   # Chạy migrate cơ sở dữ liệu
   docker compose exec web ./manage.py migrate

   # Tạo tài khoản Superuser đầu tiên
   docker compose exec web ./manage.py createsuperuser
   ```
3. **Đăng nhập và tạo Project:**
   * Truy cập giao diện tại cổng `8080` (hoặc domain HTTPS qua proxy).
   * Đăng nhập bằng tài khoản superuser vừa tạo.
   * Tạo một Tổ chức (Organization) mới và một Dự án (Project) tên là: `tradingview-bot`.
   * Lấy địa chỉ **DSN** của dự án vừa tạo (định dạng `https://<key>@<domain>/<project-id>`) để cấu hình vào `.env` của VPS giao dịch.

---

## 3. Cấu hình Nginx Reverse Proxy & SSL (HTTPS)

Để VPS giao dịch có thể đẩy log từ xa qua Internet một cách an toàn, cấu hình block server sau trong Nginx trên Monitor VPS (hoặc sử dụng Cloudflare Tunnels):

```nginx
server {
    listen 8443 ssl http2;
    server_name monitor.pesil.me; # Thay bằng domain của anh

    ssl_certificate /etc/letsencrypt/live/monitor.pesil.me/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/monitor.pesil.me/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Sentry SDK yêu cầu kết nối websockets ổn định cho một số tính năng APM
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## 4. Quy trình Backup & Dọn dẹp Định kỳ (Maintenance)

1. **Backup PostgreSQL Database:**
   Thiết lập một cron job hàng ngày để sao lưu dữ liệu GlitchTip:
   ```bash
   tar -czf /backup/glitchtip_pg_$(date +\%F).tar.gz /var/lib/docker/volumes/glitchtip_pg-data/_data
   ```
2. **Cron dọn dẹp (Clean old events):**
   GlitchTip tự động xóa các sự kiện cũ nhờ biến `GLITCHTIP_MAX_EVENT_LIFE_DAYS=30`. Để tối ưu hóa lại không gian vật lý của PostgreSQL, chạy lệnh `VACUUM` hàng tuần:
   ```bash
   0 3 * * 0 docker compose exec -T postgres vacuumdb -U glitchtip -d glitchtip --analyze-only
   ```
