"""
live_dashboard_server.py — Lightweight Proxy Server for live dashboard on port 8080.
Forces mode=FORWARD on all API requests to ensure data consistency.
"""

import logging
import sys
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
import httpx
import uvicorn

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("live_dashboard_proxy")

app = FastAPI(
    title="Angati Live Dashboard Proxy",
    description="Proxies port 8080 to port 5000, forcing FORWARD mode for consistency.",
)

PROJECT_ROOT = Path(__file__).resolve().parent
STATIC_DIR = PROJECT_ROOT / "static"

# Shared HTTP client for proxying
client = httpx.AsyncClient(base_url="http://127.0.0.1:5000", follow_redirects=False)


@app.get("/dashboard_live.html", response_class=HTMLResponse)
async def serve_dashboard_live():
    """Serve the live dashboard page directly."""
    log.info("Serving dashboard_live.html")
    dashboard_file = STATIC_DIR / "dashboard.html"
    if not dashboard_file.exists():
        log.error(f"dashboard.html not found at {dashboard_file}")
        return Response(content="dashboard.html not found", status_code=404)
    return FileResponse(str(dashboard_file))


@app.get("/forward_test.html", response_class=HTMLResponse)
async def serve_forward_test():
    """Serve the forward test page directly."""
    log.info("Serving forward_test.html")
    ft_file = STATIC_DIR / "forward_test.html"
    if not ft_file.exists():
        log.error(f"forward_test.html not found at {ft_file}")
        return Response(content="forward_test.html not found", status_code=404)
    return FileResponse(str(ft_file))


@app.get("/", response_class=HTMLResponse)
async def serve_root():
    """Redirect or serve dashboard page from root."""
    return await serve_dashboard_live()


@app.api_route(
    "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"]
)
async def proxy_request(request: Request, path: str):
    """Proxy all other requests to port 5000 FastAPI server, injecting mode=FORWARD for API routes."""
    url = f"/{path}"

    # Extract query params
    params = dict(request.query_params)

    # Check if request is an API/trades endpoint that requires mode=FORWARD
    is_api = any(
        path.startswith(prefix)
        for prefix in ["trades", "api", "webhook", "auth", "tv_health_check"]
    )

    if is_api:
        # Force FORWARD mode to guarantee consistency with forward_trades.db
        params["mode"] = "FORWARD"
        log.info(f"Proxying API: {request.method} {url} with mode=FORWARD")
    else:
        log.debug(f"Proxying asset: {request.method} {url}")

    # Read request body
    body = await request.body()

    # Forward headers (excluding host to prevent routing issues)
    headers = dict(request.headers)
    headers.pop("host", None)

    try:
        response = await client.request(
            method=request.method,
            url=url,
            params=params,
            headers=headers,
            content=body,
        )
    except Exception as e:
        log.error(f"Failed to proxy request {request.method} {url}: {e}")
        return Response(content=f"Proxy error: {str(e)}", status_code=502)

    # Forward response headers (excluding content-length and transfer-encoding)
    excluded_headers = [
        "content-encoding",
        "content-length",
        "transfer-encoding",
        "connection",
    ]
    resp_headers = {
        k: v for k, v in response.headers.items() if k.lower() not in excluded_headers
    }

    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=resp_headers,
    )


if __name__ == "__main__":
    log.info("Starting live dashboard proxy on port 8080...")
    try:
        uvicorn.run(app, host="127.0.0.1", port=8080, log_level="info")
    except Exception as e:
        log.exception(f"Uvicorn run failed: {e}")
        sys.exit(1)
