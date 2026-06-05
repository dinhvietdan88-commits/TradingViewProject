from unittest.mock import MagicMock, patch
from PIL import Image

from notifier import prepare_telegram_photo, send_telegram_photo


def test_prepare_telegram_photo_non_existent(tmp_path):
    """Should return None if file does not exist."""
    fake_path = tmp_path / "non_existent.png"
    assert prepare_telegram_photo(fake_path) is None


def test_prepare_telegram_photo_png(tmp_path):
    """Should preserve PNG file contents and return seeked BytesIO with original name."""
    img_path = tmp_path / "test_chart.png"
    img = Image.new("RGB", (100, 100), color="red")
    img.save(img_path, format="PNG")

    buf = prepare_telegram_photo(img_path)
    assert buf is not None
    assert buf.name == "test_chart.png"

    # Verify it can be opened and is indeed PNG format
    opened_img = Image.open(buf)
    assert opened_img.format == "PNG"


def test_prepare_telegram_photo_webp(tmp_path):
    """Should convert WebP file to PNG in-memory and return seeked BytesIO named .png."""
    img_path = tmp_path / "test_chart.webp"
    img = Image.new("RGB", (100, 100), color="blue")
    img.save(img_path, format="WEBP")

    buf = prepare_telegram_photo(img_path)
    assert buf is not None
    assert buf.name == "test_chart.png"

    # Verify it was converted to PNG
    opened_img = Image.open(buf)
    assert opened_img.format == "PNG"
    assert opened_img.size == (100, 100)


@patch("requests.post")
@patch("config.TELEGRAM_BOT_TOKEN", "fake_token")
@patch("config.TELEGRAM_CHAT_IDS", ["123456"])
def test_send_telegram_photo_webp(mock_post, tmp_path):
    """Verify send_telegram_photo converts WebP image and sends it with correct content type."""
    img_path = tmp_path / "test_chart.webp"
    img = Image.new("RGB", (50, 50), color="green")
    img.save(img_path, format="WEBP")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_post.return_value = mock_resp

    send_telegram_photo(img_path, "Test WebP photo")

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert "fake_token" in args[0]

    # Check multipart files
    files = kwargs["files"]
    assert "photo" in files
    filename, file_obj, mime_type = files["photo"]
    assert filename == "test_chart.png"
    assert mime_type == "image/png"

    # Verify the file_obj is a valid converted PNG
    opened_img = Image.open(file_obj)
    assert opened_img.format == "PNG"
