import pytest
import aiohttp
from unittest.mock import AsyncMock, MagicMock
from agy_harness import AgyHarness


class MockResponse:
    def __init__(self, status, json_data=None, text_data=""):
        self.status = status
        self._json = json_data or {}
        self._text = text_data

    async def json(self):
        return self._json

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
async def test_agy_harness_init(mocker):
    mocker.patch.dict("os.environ", {"AGY_BRIDGE_SECRET": "env-secret"})
    harness = AgyHarness(
        bridge_url="http://localhost:9100/",
        timeout_sec=10,
        max_retries=2,
        model="test-model",
    )
    assert harness.bridge_url == "http://localhost:9100"
    assert harness.timeout_sec == 10
    assert harness.max_retries == 2
    assert harness.model == "test-model"
    assert harness._secret == "env-secret"  # noqa: S105


@pytest.mark.asyncio
async def test_agy_harness_session_lazy(mocker):
    mock_session_class = mocker.patch("aiohttp.ClientSession")
    mock_session = mock_session_class.return_value
    mock_session.closed = False
    mock_session.close = AsyncMock()

    harness = AgyHarness()
    session = await harness._get_session()
    assert session is mock_session
    mock_session_class.assert_called_once()

    session2 = await harness._get_session()
    assert session2 is mock_session

    await harness.close()
    mock_session.close.assert_called_once()
    assert harness._session is None


@pytest.mark.asyncio
async def test_agy_harness_check_health_success(mocker):
    mock_session_class = mocker.patch("aiohttp.ClientSession")
    mock_session = mock_session_class.return_value
    mock_session.closed = False

    mock_resp = MockResponse(
        200, json_data={"status": "ok", "circuit_breaker": {"state": "CLOSED"}}
    )
    mock_session.get.return_value = mock_resp

    harness = AgyHarness()
    health = await harness.check_health()
    assert health == {"status": "ok", "circuit_breaker": {"state": "CLOSED"}}
    mock_session.get.assert_called_once()


@pytest.mark.asyncio
async def test_agy_harness_check_health_non_200(mocker):
    mock_session_class = mocker.patch("aiohttp.ClientSession")
    mock_session = mock_session_class.return_value
    mock_session.closed = False

    mock_resp = MockResponse(500)
    mock_session.get.return_value = mock_resp

    harness = AgyHarness()
    health = await harness.check_health()
    assert health == {}


@pytest.mark.asyncio
async def test_agy_harness_check_health_exception(mocker):
    mock_session_class = mocker.patch("aiohttp.ClientSession")
    mock_session = mock_session_class.return_value
    mock_session.closed = False
    mock_session.get.side_effect = Exception("Network error")

    harness = AgyHarness()
    health = await harness.check_health()
    assert health == {}


@pytest.mark.asyncio
async def test_agy_harness_is_available(mocker):
    harness = AgyHarness()

    # CASE 1: healthy, CLOSED
    mocker.patch.object(
        harness, "check_health", return_value={"circuit_breaker": {"state": "CLOSED"}}
    )
    assert await harness.is_available() is True

    # CASE 2: healthy, OPEN
    mocker.patch.object(
        harness, "check_health", return_value={"circuit_breaker": {"state": "OPEN"}}
    )
    assert await harness.is_available() is False

    # CASE 3: unreachable
    mocker.patch.object(harness, "check_health", return_value={})
    assert await harness.is_available() is False


@pytest.mark.asyncio
async def test_agy_harness_analyze_success(mocker):
    mock_session_class = mocker.patch("aiohttp.ClientSession")
    mock_session = mock_session_class.return_value
    mock_session.closed = False

    mock_resp = MockResponse(
        200,
        json_data={
            "advice": "This is a great advice from AI.",
            "model": "gemini",
            "latency_ms": 120,
        },
    )
    mock_session.post.return_value = mock_resp

    harness = AgyHarness(secret="custom-secret")
    res = await harness.analyze("Test prompt", system_instruction="system instruct")
    assert res.success is True
    assert res.advice == "This is a great advice from AI."
    assert res.model == "gemini"
    assert res.latency_ms == 120
    assert res.error is None

    # check headers/payload
    mock_session.post.assert_called_once()
    args, kwargs = mock_session.post.call_args
    assert kwargs["headers"] == {"Authorization": "Bearer custom-secret"}
    assert kwargs["json"]["prompt"] == "Test prompt"
    assert kwargs["json"]["system_instruction"] == "system instruct"


@pytest.mark.asyncio
async def test_agy_harness_analyze_empty_response(mocker):
    mock_session_class = mocker.patch("aiohttp.ClientSession")
    mock_session = mock_session_class.return_value
    mock_session.closed = False

    mock_resp = MockResponse(
        200, json_data={"advice": "short", "model": "gemini", "latency_ms": 120}
    )
    mock_session.post.return_value = mock_resp

    harness = AgyHarness()
    res = await harness.analyze("Test prompt")
    assert res.success is False
    assert res.error == "Response too short or empty"


@pytest.mark.asyncio
async def test_agy_harness_analyze_503_cb_open(mocker):
    mock_session_class = mocker.patch("aiohttp.ClientSession")
    mock_session = mock_session_class.return_value
    mock_session.closed = False

    mock_resp = MockResponse(503, text_data="Circuit Breaker Open")
    mock_session.post.return_value = mock_resp

    harness = AgyHarness(max_retries=2)
    res = await harness.analyze("Test prompt")
    assert res.success is False
    assert "Bridge CB OPEN" in res.error
    # Should exit immediately without retries
    assert mock_session.post.call_count == 1


@pytest.mark.asyncio
async def test_agy_harness_analyze_504_retry_and_fail(mocker):
    mock_session_class = mocker.patch("aiohttp.ClientSession")
    mock_session = mock_session_class.return_value
    mock_session.closed = False

    mock_resp = MockResponse(504, text_data="Gateway Timeout")
    mock_session.post.return_value = mock_resp

    # mock sleep to speed up test
    mock_sleep = mocker.patch("asyncio.sleep", return_value=None)

    harness = AgyHarness(max_retries=1)
    res = await harness.analyze("Test prompt")
    assert res.success is False
    assert "Timeout:" in res.error
    assert mock_session.post.call_count == 2
    assert mock_sleep.call_count == 1


@pytest.mark.asyncio
async def test_agy_harness_analyze_connector_error(mocker):
    mock_session_class = mocker.patch("aiohttp.ClientSession")
    mock_session = mock_session_class.return_value
    mock_session.closed = False

    mock_session.post.side_effect = aiohttp.ClientConnectorError(
        connection_key=MagicMock(), os_error=OSError()
    )

    harness = AgyHarness(max_retries=2)
    res = await harness.analyze("Test prompt")
    assert res.success is False
    assert "Connection refused" in res.error
    # Should break early on connection refused
    assert mock_session.post.call_count == 1


@pytest.mark.asyncio
async def test_agy_harness_context_manager(mocker):
    mock_session_class = mocker.patch("aiohttp.ClientSession")
    mock_session = mock_session_class.return_value
    mock_session.closed = False
    mock_session.close = AsyncMock()

    async with AgyHarness() as harness:
        await harness._get_session()
        assert harness._session is mock_session

    mock_session.close.assert_called_once()
