"""
Auth Routes — FastAPI endpoints for authentication flow.

Endpoints:
- GET  /auth/login          — Serve login page
- GET  /auth/callback       — Exchange one-time code for session
- POST /auth/telegram-callback — Telegram Login Widget callback
- GET  /auth/logout         — Invalidate session and redirect
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

log = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/auth", tags=["auth"])


def _get_auth_service(request: Request):
    """Retrieve AuthService from app state."""
    return getattr(request.app.state, "auth_service", None)


@auth_router.get("/login")
async def login_page(request: Request, next: Optional[str] = Query(default="/")):
    """Serve the login page.

    If Telegram Login Widget is enabled, includes the widget script.
    Otherwise shows instructions to use /login bot command.
    """
    from pathlib import Path

    login_html_path = Path(__file__).parent.parent / "static" / "login.html"
    if login_html_path.exists():
        content = login_html_path.read_text(encoding="utf-8")
        # Inject next URL
        content = content.replace("{{NEXT_URL}}", next or "/")
        return HTMLResponse(content=content)

    # Fallback if login.html not found
    return HTMLResponse(
        content="""
        <html><body style="background:#0f0f23;color:#e2e8f0;font-family:sans-serif;
        display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
        <div style="text-align:center">
            <h1>🔐 Dashboard Login</h1>
            <p>Use <code>/login</code> in the Telegram Bot to get a login link.</p>
        </div>
        </body></html>
        """,
        status_code=200,
    )


@auth_router.get("/callback")
async def auth_callback(request: Request, code: str = Query(...)):
    """Exchange a one-time code for a session cookie.

    Flow:
    1. Look up code in DB
    2. AuthService.exchange_code() validates and creates session
    3. Mark code as used in DB
    4. Store session in DB
    5. Set tg_session cookie
    6. Redirect to dashboard
    """
    from auth.models import (
        CodeInvalidError,
        CodeExpiredError,
        CodeUsedError,
        UserNotAllowedError,
    )

    auth_service = _get_auth_service(request)
    if auth_service is None:
        return JSONResponse(
            status_code=503, content={"detail": "Auth service not available"}
        )

    try:
        import database as db

        # Fetch code record from DB
        code_record = db.get_auth_code(code)

        # Validate and create session
        session = auth_service.exchange_code(code_record, code)

        # Mark code as used
        db.mark_auth_code_used(code)

        # Store session in DB
        db.store_auth_session(
            session_id=session.session_id,
            telegram_id=session.telegram_id,
            username=session.username,
            created_at=session.created_at.isoformat(),
            expires_at=session.expires_at.isoformat() if session.expires_at else None,
        )

        # Create signed token
        token = auth_service.create_session_token(session)

        # Set cookie and redirect
        response = RedirectResponse(url="/", status_code=302)
        max_age = (
            auth_service.config.session_expiry_hours * 3600
            if auth_service.config.session_expiry_hours
            else 7 * 24 * 3600
        )
        response.set_cookie(
            key="tg_session",
            value=token,
            httponly=True,
            secure=False,  # Set True with HTTPS
            samesite="lax",
            max_age=max_age,
            path="/",
        )

        log.info(
            f"Login successful for user {session.telegram_id} "
            f"(session: {session.session_id[:8]}...)"
        )
        return response

    except CodeInvalidError:
        return _error_page("Mã đăng nhập không hợp lệ", "Code không tồn tại hoặc đã bị sai.", 401)
    except CodeExpiredError:
        return _error_page("Mã đã hết hạn", "Vui lòng dùng /login để tạo mã mới.", 401)
    except CodeUsedError:
        return _error_page("Mã đã được sử dụng", "Mỗi mã chỉ dùng được 1 lần. Dùng /login để tạo mã mới.", 401)
    except UserNotAllowedError:
        return _error_page("Truy cập bị từ chối", "Tài khoản của bạn không được phép truy cập Dashboard.", 403)
    except Exception as e:
        log.error(f"Auth callback error: {e}", exc_info=True)
        return _error_page("Lỗi xác thực", f"Đã xảy ra lỗi: {e}", 500)


@auth_router.post("/telegram-callback")
async def telegram_widget_callback(request: Request):
    """Handle Telegram Login Widget callback.

    Receives widget data, verifies HMAC, creates session.
    """
    from auth.models import (
        WidgetHashInvalidError,
        WidgetExpiredError,
        UserNotAllowedError,
    )

    auth_service = _get_auth_service(request)
    if auth_service is None:
        return JSONResponse(
            status_code=503, content={"detail": "Auth service not available"}
        )

    if not auth_service.config.widget_enabled:
        return JSONResponse(
            status_code=403, content={"detail": "Widget authentication disabled"}
        )

    try:
        data = await request.json()
        user = auth_service.verify_widget_data(data)

        # Create session
        from auth.models import SessionData
        import uuid
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        if auth_service.config.session_expiry_hours is None:
            expires_at = None
            never_expires = True
        else:
            expires_at = now + timedelta(hours=auth_service.config.session_expiry_hours)
            never_expires = False

        session = SessionData(
            session_id=str(uuid.uuid4()),
            telegram_id=user.telegram_id,
            username=user.username,
            created_at=now,
            expires_at=expires_at,
            never_expires=never_expires,
        )

        # Store in DB
        import database as db
        db.store_auth_session(
            session_id=session.session_id,
            telegram_id=session.telegram_id,
            username=session.username,
            created_at=session.created_at.isoformat(),
            expires_at=session.expires_at.isoformat() if session.expires_at else None,
        )

        token = auth_service.create_session_token(session)

        return JSONResponse(content={
            "success": True,
            "token": token,
            "user": {
                "telegram_id": user.telegram_id,
                "username": user.username,
                "display_name": user.display_name,
            }
        })

    except WidgetHashInvalidError:
        return JSONResponse(status_code=401, content={"detail": "Invalid widget data"})
    except WidgetExpiredError:
        return JSONResponse(status_code=401, content={"detail": "Widget auth expired"})
    except UserNotAllowedError:
        return JSONResponse(status_code=403, content={"detail": "User not authorized"})
    except Exception as e:
        log.error(f"Widget callback error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": str(e)})


@auth_router.get("/logout")
async def logout(request: Request):
    """Invalidate session and redirect to login."""
    auth_service = _get_auth_service(request)

    # Try to invalidate session in DB
    token = request.cookies.get("tg_session")
    if token and auth_service:
        try:
            session = auth_service.verify_session_token(token)
            import database as db
            db.delete_auth_session(session.session_id)
            auth_service.invalidate_session(session.session_id)
        except Exception:
            pass  # Session already invalid/expired — just clear cookie

    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie("tg_session", path="/")
    return response


def _error_page(title: str, message: str, status_code: int = 401) -> HTMLResponse:
    """Render a styled error page in Vietnamese."""
    return HTMLResponse(
        content=f"""
        <!DOCTYPE html>
        <html lang="vi">
        <head><meta charset="utf-8"><title>{title}</title>
        <style>
            body {{ background:#0f0f23; color:#e2e8f0; font-family:'Inter',sans-serif;
                    display:flex; align-items:center; justify-content:center;
                    height:100vh; margin:0; }}
            .card {{ background:rgba(30,30,60,0.9); border:1px solid rgba(255,255,255,0.08);
                     border-radius:16px; padding:2.5rem; max-width:420px; text-align:center; }}
            h2 {{ color:#f87171; margin-bottom:0.5rem; }}
            p {{ color:#94a3b8; line-height:1.6; }}
            a {{ color:#818cf8; text-decoration:none; }}
            a:hover {{ text-decoration:underline; }}
        </style></head>
        <body><div class="card">
            <h2>⚠️ {title}</h2>
            <p>{message}</p>
            <p><a href="/auth/login">← Quay lại trang đăng nhập</a></p>
        </div></body></html>
        """,
        status_code=status_code,
    )
