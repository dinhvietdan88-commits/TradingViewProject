# 🌐 Cấu hình Cloudflare Zero Trust & Cloudflare Workers cho TradingView Webhook

Hướng dẫn này giúp sếp thiết lập một **Tên miền cố định (Custom Domain)** và cấu hình **Cloudflare Access (Zero Trust)** hoặc **Cloudflare Workers** để TradingView có thể gửi tín hiệu Webhook an toàn mà không bị chặn bởi tường lửa xác thực.

---

## 🛠️ Giải pháp 1: Sử dụng Cloudflare Tunnel (Cố định) + Access Bypass
Đây là giải pháp khuyến nghị. Sếp sẽ dùng một tên miền riêng (ví dụ: `bot.yourdomain.com`) được bảo vệ bởi Cloudflare Access, nhưng chừa riêng đường dẫn `/webhook` cho TradingView.

### Bước 1: Tạo Named Tunnel (Tunnel cố định)
Thay vì dùng Quick Tunnel sinh URL ngẫu nhiên, sếp tạo một Tunnel định danh trên máy:
```bash
# 1. Đăng nhập vào Cloudflare từ CLI
cloudflared tunnel login

# 2. Tạo một tunnel mới (ví dụ tên là: mj-trading-tunnel)
cloudflared tunnel create mj-trading-tunnel
```
*Lệnh này sẽ tạo ra một file credentials `.json` trong thư mục `~/.cloudflared/`.*

### Bước 2: Cấu hình file `config.yml`
Tạo file `config.yml` trong thư mục `~/.cloudflared/` (hoặc thư mục dự án):
```yaml
tunnel: <TUNNEL_ID_CỦA_SẾP>
credentials-file: C:\Users\pesil\.cloudflared\<TUNNEL_ID_CỦA_SẾP>.json

ingress:
  - hostname: bot.yourdomain.com
    service: http://localhost:5000
  - service: http_status:404
```

### Bước 3: Định cấu hình DNS trên Cloudflare Dashboard
Đăng ký tên miền phụ trỏ về tunnel:
```bash
cloudflared tunnel route dns mj-trading-tunnel bot.yourdomain.com
```

### Bước 4: Cấu hình Bypass trên Cloudflare Access (Zero Trust)
Nếu sếp bật Cloudflare Access bảo vệ domain `bot.yourdomain.com` (yêu cầu OTP/Google Login khi vào Dashboard):
1. Truy cập **Cloudflare Zero Trust Dashboard** -> **Access** -> **Applications**.
2. Chọn **Add an Application** -> **Self-Hosted**.
3. Cấu hình ứng dụng:
   * Application Name: `TradingView Webhook Ingress`
   * Domain: `bot.yourdomain.com/webhook` (Chỉ áp dụng chính xác cho đường dẫn nhận webhook).
4. Trong phần **Policies** (Chính sách):
   * Rule Name: `Bypass TradingView IP`
   * Action: **Bypass** (Cho phép đi qua không cần đăng nhập).
   * **Configure Rules** (Thiết lập điều kiện):
     * *Cách A (Khuyên dùng):* Chọn **IP Ranges** và thêm các IP của TradingView. Danh sách IP chính thức được cập nhật liên tục tại: [TradingView IP Addresses](https://www.tradingview.com/support/solutions/43000529348-about-webhooks-and-our-ip-addresses/)
     * *Cách B (Đơn giản):* Chọn **Everyone** (vì bản thân FastAPI đã có tầng bảo mật bằng khóa `WEBHOOK_SECRET` trong payload).

---

## ⚡ Giải pháp 2: Sử dụng Cloudflare Workers làm Gateway Trung Gian
Nếu sếp không muốn cấu hình Bypass trên Access, sếp có thể viết một Cloudflare Worker làm trạm trung chuyển tín hiệu.

```
TradingView Alert  ──(HTTP POST)──>  Cloudflare Worker (Công khai)
                                              │ (Xác thực Secret + Forward)
                                              ▼
Local Server FastAPI  <──(Tunnel)──  Cloudflare Access Application (Bảo mật)
```

### Bước 1: Deploy Cloudflare Worker
Tạo một Worker mới trên Cloudflare với mã nguồn sau:

```javascript
export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Chỉ chấp nhận POST tới đường dẫn /webhook
    if (request.method !== "POST" || url.pathname !== "/webhook") {
      return new Response("Method not allowed", { status: 405 });
    }

    try {
      const body = await request.clone().json();

      // Kiểm tra sơ bộ trường Secret trong JSON Payload gửi từ TV
      if (!body.secret || body.secret !== env.WEBHOOK_SECRET) {
        return new Response("Unauthorized Payload", { status: 401 });
      }

      // Gửi yêu cầu tiếp nối (Forward) vào server nội bộ thông qua Service Token của Access
      const targetUrl = `https://bot.yourdomain.com/webhook`;
      const modifiedRequest = new Request(targetUrl, {
        method: "POST",
        headers: {
          ...request.headers,
          "Content-Type": "application/json",
          // Sử dụng Access Service Token để đi xuyên qua Access Portal
          "CF-Access-Client-Id": env.CF_ACCESS_CLIENT_ID,
          "CF-Access-Client-Secret": env.CF_ACCESS_CLIENT_SECRET,
        },
        body: JSON.stringify(body)
      });

      const response = await fetch(modifiedRequest);
      return new Response(await response.text(), {
        status: response.status,
        headers: response.headers
      });

    } catch (err) {
      return new Response("Invalid JSON or internal error", { status: 400 });
    }
  }
};
```

### Bước 2: Thiết lập Service Token trong Zero Trust
1. Vào **Zero Trust** -> **Access** -> **Service Tokens** -> **Create Service Token**.
2. Copy `Client ID` và `Client Secret` vừa tạo.
3. Cấu hình 2 giá trị này làm biến môi trường (`Environment Variables`) trong Worker của sếp.
4. Tạo một **Bypass Policy** trên ứng dụng Access cho phép các request chứa Service Token này đi thẳng vào.

---

## 📈 Ưu điểm của giải pháp này
* **Không đổi URL:** Sếp chỉ cần cấu hình Alert trên TradingView một lần duy nhất vào `https://bot.yourdomain.com/webhook`.
* **Tuyệt đối an toàn:** Dashboard quản lý vẫn được khóa chặt bằng Cloudflare Access, chỉ có luồng dữ liệu thô `/webhook` được mở riêng dựa trên IP Whitelist của TradingView hoặc mã khóa bí mật.
