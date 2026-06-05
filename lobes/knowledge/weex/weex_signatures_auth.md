# WEEX API Authentication and Signatures Guide

This document details the authentication and signing rules for both V2 and V3 endpoints on the WEEX exchange.

## Overview of Authentication Headers

Every authenticated request to the WEEX API must include the following HTTP headers:

*   `ACCESS-KEY`: Your API Key string.
*   `ACCESS-SIGN`: The generated signature string (Base64-encoded).
*   `ACCESS-TIMESTAMP`: The current millisecond epoch timestamp (e.g., `1672531200000`).
*   `ACCESS-PASSPHRASE`: The passphrase set during API key creation.
*   `Content-Type`: Set to `application/json` (for POST requests).

## Key Difference: V2 vs V3 Concatenation Rules

The message payload to be signed is constructed by concatenating:
`timestamp + method + request_path + body`

The fundamental difference lies in how query parameters in GET or DELETE requests are treated:

### 1. V2 Signing Rule
In V2, the request path can natively contain the query string as part of the path.
*   **Example Path**: `/api/v2/mix/order/placeOrder?symbol=BTCUSDT_UMCBL`
*   **Message Construction**: `timestamp + "POST" + "/api/v2/mix/order/placeOrder?symbol=BTCUSDT_UMCBL" + body`
*   Query parameters are appended directly inside the `request_path` string.

### 2. V3 Signing Rule
In V3, the request path and query parameters are decoupled. The signature generator must explicitly join the base request path and sorted query parameters using a `?` character.
*   **Decoupled Components**:
    *   Path: `/api/v3/mix/order/placeOrder`
    *   Query parameters: `{"symbol": "BTCUSDT_UMCBL"}`
*   **Message Construction**: The query parameters must be sorted alphabetically by key and concatenated as a query string (e.g., `symbol=BTCUSDT_UMCBL`), then appended to the path separated by `?`.
*   **Resulting Message**: `timestamp + "POST" + "/api/v3/mix/order/placeOrder?symbol=BTCUSDT_UMCBL" + body`

## Python Executable Code Example

Below is a complete, executable Python example demonstrating the difference in signature generation.

```python
import hmac
import hashlib
import time
import base64

def generate_weex_signature_v2(api_secret, timestamp, method, request_path, body=""):
    # V2 signature uses the raw path directly (which may contain inline query parameters)
    message = f"{timestamp}{method.upper()}{request_path}{body}"
    signature = hmac.new(
        api_secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).digest()
    return base64.b64encode(signature).decode('utf-8')

def generate_weex_signature_v3(api_secret, timestamp, method, request_path, query_params=None, body=""):
    # V3 signature explicitly decouples query parameters, sorts them, and joins them with '?'
    query_str = ""
    if query_params:
        sorted_keys = sorted(query_params.keys())
        query_str = "&".join(f"{k}={query_params[k]}" for k in sorted_keys)

    full_path = request_path
    if query_str:
        full_path = f"{request_path}?{query_str}"

    message = f"{timestamp}{method.upper()}{full_path}{body}"
    signature = hmac.new(
        api_secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).digest()
    return base64.b64encode(signature).decode('utf-8')

# Example Verification Run
if __name__ == "__main__":
    secret = "my_weex_secret_key"
    ts = "1680000000000"
    method = "GET"
    path = "/api/v3/spot/order"
    params = {"orderId": "992831", "symbol": "BTCUSDT"}

    # Generate signature with sorted parameters for V3
    sig_v3 = generate_weex_signature_v3(secret, ts, method, path, params)
    print("V3 Signature:", sig_v3)

    # Matching V2 equivalent with pre-formatted path
    v2_path = f"{path}?orderId=992831&symbol=BTCUSDT"
    sig_v2 = generate_weex_signature_v2(secret, ts, method, v2_path)
    print("V2 Equivalent Signature:", sig_v2)
    assert sig_v3 == sig_v2, "V2 and V3 signatures should match when paths are equivalent"
```
