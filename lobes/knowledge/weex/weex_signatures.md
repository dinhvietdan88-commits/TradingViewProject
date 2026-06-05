# WEEX Signature Calculation and Authentication

## 1. Authentication Headers

All private/authenticated REST API and WebSocket login requests require API keys and cryptographic signatures. The signature must be computed and sent along with the following HTTP headers:

*   `ACCESS-KEY`: The user's unique API Key (provided by WEEX).
*   `ACCESS-SIGN`: The calculated HMAC-SHA256 signature (Base64-encoded).
*   `ACCESS-TIMESTAMP`: The current epoch timestamp in milliseconds (e.g., `1684812345000`).
*   `ACCESS-PASSPHRASE`: The passphrase defined by the user during API Key creation.
*   `Content-Type`: Must be `application/json` for REST requests.

---

## 2. Signature Payload Format

The signature payload string is constructed by concatenating specific request fields in the following order:

*   **Format when Query String is Empty (or POST requests with body):**
    ```
    timestamp + METHOD + requestPath + body
    ```
*   **Format when Query String is Not Empty (typically GET/DELETE requests with query parameters):**
    ```
    timestamp + METHOD + requestPath + "?" + queryString + body
    ```

### 2.1 Description of Fields
*   `timestamp`: The exact string value passed in the `ACCESS-TIMESTAMP` header (e.g., `1684812345000`).
*   `METHOD`: The HTTP request method in uppercase (e.g., `GET`, `POST`, `DELETE`).
*   `requestPath`: The relative path of the request, excluding query parameters (e.g., `/api/v3/order` or `/api/v1/spot/trade/order_info`).
*   `queryString`: The raw query parameters after the `?` in the URL (e.g., `symbol=BTCUSDT&limit=20`).
*   `body`: The JSON string body of the request (for `POST` or `PUT` requests). If there is no body (e.g., a `GET` request or `POST` request with an empty body), this must be an empty string (`""`).

> [!NOTE]
> For V2 APIs, the signature string can also be constructed by treating `requestPath` as containing the query string (e.g. `requestPath` = `/api/v1/spot/trade/order_info?symbol=BTCUSDT&orderId=1234567890`), which yields the same concatenated result. The V3 specifications explicitly decouple the base path and the query string.

---

## 3. Executable Python Signing Example

The following is a complete, executable Python code snippet showing how to generate the HMAC-SHA256 signature, encode it as Base64, and prepare the request headers:

```python
import hmac
import hashlib
import base64
import time

def generate_weex_signature(secret_key: str, timestamp: str, method: str, request_path: str, body: str = "") -> str:
    """
    Generates the HMAC-SHA256 signature for WEEX platform authentication.

    :param secret_key: The API Secret Key.
    :param timestamp: The string timestamp in milliseconds.
    :param method: The HTTP method (GET, POST, etc.) in uppercase.
    :param request_path: The relative API endpoint path with query parameters.
    :param body: The raw JSON body string for POST requests, or empty string.
    :return: Base64 encoded signature string.
    """
    # 1. Construct signature payload string
    payload = f"{timestamp}{method.upper()}{request_path}{body}"

    # 2. Compute HMAC-SHA256 signature using the secret key
    mac = hmac.new(
        bytes(secret_key, encoding='utf-8'),
        bytes(payload, encoding='utf-8'),
        digestmod=hashlib.sha256
    )

    # 3. Base64 encode the binary HMAC output and convert to string
    signature = base64.b64encode(mac.digest()).decode('utf-8')
    return signature

# --- Example Invocations ---
if __name__ == "__main__":
    # Sample user credentials (must be replaced with real API credentials in production)
    API_KEY = "weex_api_key_sample_123"
    SECRET_KEY = "weex_secret_key_sample_456"
    PASSPHRASE = "weex_passphrase_sample_789"

    # 1. Sign a GET Request Example (e.g. order detail check)
    timestamp_get = "1684812345000"
    method_get = "GET"
    path_get = "/api/v1/spot/trade/order_info?symbol=BTCUSDT&orderId=8877665544332211"

    sign_get = generate_weex_signature(
        secret_key=SECRET_KEY,
        timestamp=timestamp_get,
        method=method_get,
        request_path=path_get
    )

    print("--- GET Request Signature Details ---")
    print(f"Timestamp: {timestamp_get}")
    print(f"Signature: {sign_get}")
    print(f"Expected signature format: Base64 HMAC-SHA256")

    # 2. Sign a POST Request Example (e.g. place spot order)
    timestamp_post = "1684812348000"
    method_post = "POST"
    path_post = "/api/v1/spot/trade/order"
    body_post = '{"symbol":"BTCUSDT","side":"buy","type":"limit","price":"27500.50","quantity":"0.005","clientOrderId":"cl_ord_spot_001"}'

    sign_post = generate_weex_signature(
        secret_key=SECRET_KEY,
        timestamp=timestamp_post,
        method=method_post,
        request_path=path_post,
        body=body_post
    )

    print("\n--- POST Request Signature Details ---")
    print(f"Timestamp: {timestamp_post}")
    print(f"Signature: {sign_post}")

    # 3. Headers Dict Example
    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign_post,
        "ACCESS-TIMESTAMP": timestamp_post,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json"
    }
    print("\nHeaders dict:")
    for key, val in headers.items():
        print(f"  {key}: {val}")
```
