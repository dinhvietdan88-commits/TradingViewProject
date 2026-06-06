"""
test_db_schema_parity.py — Kiểm tra tính nhất quán schema database.

Đảm bảo init_db() tạo đúng bảng với đúng cột, và gọi nhiều lần
không gây lỗi (idempotent).
"""

import aiosqlite
import pytest
import pytest_asyncio


@pytest.fixture
def db_path(tmp_path):
    """Tạo đường dẫn DB tạm trong tmp_path."""
    return str(tmp_path / "test_schema.db")


@pytest_asyncio.fixture
async def initialized_db(db_path):
    """Init DB vào temp file và trả về path để query trực tiếp."""
    import config
    import database

    original_path = config.DB_PATH
    original_timeout = config.DB_TIMEOUT
    config.DB_PATH = db_path
    config.DB_TIMEOUT = 30.0

    await database.init_db()

    yield db_path

    config.DB_PATH = original_path
    config.DB_TIMEOUT = original_timeout


async def _get_tables(db_path: str) -> list[str]:
    """Helper: lấy danh sách tên bảng từ sqlite_master."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]


async def _get_columns(db_path: str, table_name: str) -> list[str]:
    """Helper: lấy danh sách tên cột của một bảng qua PRAGMA table_info."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(f"PRAGMA table_info({table_name})") as cursor:
            rows = await cursor.fetchall()
            # PRAGMA table_info returns: (cid, name, type, notnull, dflt_value, pk)
            return [r[1] for r in rows]


# ── Test 1: signals table ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_tables_creates_signals_table(initialized_db):
    """Sau init_db(), bảng 'signals' phải tồn tại với các cột cần thiết."""
    tables = await _get_tables(initialized_db)
    assert "signals" in tables, f"Table 'signals' not found. Existing tables: {tables}"

    columns = await _get_columns(initialized_db, "signals")
    required_columns = {"id", "symbol", "action", "price", "created_at"}
    missing = required_columns - set(columns)
    assert not missing, (
        f"signals table missing columns: {missing}. Actual columns: {columns}"
    )


# ── Test 2: orders / trades table ──────────────────────────────────────


@pytest.mark.asyncio
async def test_create_tables_creates_orders_table(initialized_db):
    """Sau init_db(), bảng 'trades' (orders) phải tồn tại.

    Hệ thống dùng bảng 'trades' thay cho 'orders' — cả hai tên đều
    chấp nhận được. Kiểm tra bảng trades tồn tại với các cột cơ bản.
    """
    tables = await _get_tables(initialized_db)
    # The system uses 'trades' as the orders table
    assert "trades" in tables, (
        f"Table 'trades' (orders) not found. Existing tables: {tables}"
    )

    columns = await _get_columns(initialized_db, "trades")
    # Verify core order/trade columns exist
    required_columns = {"id", "signal_id", "symbol", "side", "status"}
    missing = required_columns - set(columns)
    assert not missing, (
        f"trades table missing columns: {missing}. Actual columns: {columns}"
    )


# ── Test 3: idempotent init_db() ───────────────────────────────────────


@pytest.mark.asyncio
async def test_create_tables_idempotent(db_path):
    """Gọi init_db() hai lần không gây exception — CREATE IF NOT EXISTS."""
    import config
    import database

    original_path = config.DB_PATH
    original_timeout = config.DB_TIMEOUT
    config.DB_PATH = db_path
    config.DB_TIMEOUT = 30.0

    try:
        # First call — creates everything
        await database.init_db()

        # Second call — must not raise
        await database.init_db()

        # Verify tables still intact after double init
        tables = await _get_tables(db_path)
        assert "signals" in tables
        assert "trades" in tables
        assert "settings" in tables
    finally:
        config.DB_PATH = original_path
        config.DB_TIMEOUT = original_timeout


# ── Test 4: settings table ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_tables_creates_settings_table(initialized_db):
    """Sau init_db(), bảng 'settings' phải tồn tại với cột key, value."""
    tables = await _get_tables(initialized_db)
    assert "settings" in tables, (
        f"Table 'settings' not found. Existing tables: {tables}"
    )

    columns = await _get_columns(initialized_db, "settings")
    required_columns = {"key", "value"}
    missing = required_columns - set(columns)
    assert not missing, (
        f"settings table missing columns: {missing}. Actual columns: {columns}"
    )
