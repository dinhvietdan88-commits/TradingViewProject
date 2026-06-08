"""
test_rag_remote.py — Unit tests for Remote ChromaDB Configuration (Phase 4).

Verifies:
  1. CHROMA_REMOTE=true → chromadb.HttpClient used with correct host:port
  2. CHROMA_REMOTE=false → chromadb.PersistentClient used (backward compat)
  3. Collection properly initialized in remote mode
  4. query_knowledge() works after remote init
"""

import pathlib
import sys
import importlib.util
import importlib.machinery
import types
from unittest.mock import MagicMock, patch
import pytest

# Mock importlib.util.find_spec to return a valid spec for chromadb without loading the real package
orig_find_spec = importlib.util.find_spec


def mock_find_spec(name, package=None):
    if name == "chromadb":
        return importlib.machinery.ModuleSpec("chromadb", None)
    try:
        return orig_find_spec(name, package)
    except Exception:
        return None


importlib.util.find_spec = mock_find_spec

# Mock chromadb in sys.modules to prevent opentelemetry import errors in broken environments

mock_chroma = types.ModuleType("chromadb")
mock_chroma.__file__ = "<mock chromadb>"
mock_chroma.__spec__ = importlib.machinery.ModuleSpec("chromadb", None)

mock_chroma_utils = types.ModuleType("chromadb.utils")
mock_chroma_utils.__file__ = "<mock chromadb.utils>"
mock_chroma_utils.__spec__ = importlib.machinery.ModuleSpec("chromadb.utils", None)

mock_chroma_utils_ef = types.ModuleType("chromadb.utils.embedding_functions")
mock_chroma_utils_ef.__file__ = "<mock chromadb.utils.embedding_functions>"
mock_chroma_utils_ef.__spec__ = importlib.machinery.ModuleSpec(
    "chromadb.utils.embedding_functions", None
)

mock_chroma.utils = mock_chroma_utils
mock_chroma_utils.embedding_functions = mock_chroma_utils_ef

mock_chroma.HttpClient = MagicMock()
mock_chroma.PersistentClient = MagicMock()


def dummy_ef(*args, **kwargs):
    return MagicMock()


mock_chroma_utils_ef.SentenceTransformerEmbeddingFunction = dummy_ef

sys.modules["chromadb"] = mock_chroma
sys.modules["chromadb.utils"] = mock_chroma_utils
sys.modules["chromadb.utils.embedding_functions"] = mock_chroma_utils_ef

# Ensure server/ is on sys.path so `import config` / `import rag` work
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_collection(doc_count: int = 5):
    """Create a mock ChromaDB collection with realistic behavior."""
    coll = MagicMock()
    coll.count.return_value = doc_count
    coll.query.return_value = {
        "documents": [["Doc about VCP pattern", "Doc about trend template"]],
        "metadatas": [
            [
                {"filename": "chunk_001.md", "topic": "VCP", "chapter": "001"},
                {
                    "filename": "chunk_002.md",
                    "topic": "Trend Template",
                    "chapter": "002",
                },
            ]
        ],
        "distances": [[0.15, 0.25]],
    }
    return coll


def _make_mock_http_client(collection: MagicMock):
    """Create a mock chromadb.HttpClient."""
    client = MagicMock()
    client.get_or_create_collection.return_value = collection
    return client


def _make_mock_persistent_client(collection: MagicMock):
    """Create a mock chromadb.PersistentClient."""
    client = MagicMock()
    client.get_or_create_collection.return_value = collection
    return client


# ---------------------------------------------------------------------------
# Test 1: Remote mode uses HttpClient with correct host:port
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remote_mode_uses_http_client():
    """When CHROMA_REMOTE=true, init_vector_db should use chromadb.HttpClient
    with the configured CHROMA_SERVER_HOST and CHROMA_SERVER_PORT."""
    import config
    import rag

    mock_collection = _make_mock_collection()
    mock_client = _make_mock_http_client(mock_collection)
    mock_ef = MagicMock()

    # Save originals to restore later
    orig_remote = getattr(config, "CHROMA_REMOTE", False)
    orig_host = getattr(config, "CHROMA_SERVER_HOST", "localhost")
    orig_port = getattr(config, "CHROMA_SERVER_PORT", 8000)
    orig_chroma_client = rag._chroma_client
    orig_collection = rag._collection

    try:
        config.CHROMA_REMOTE = True
        config.CHROMA_SERVER_HOST = "chroma.example.com"
        config.CHROMA_SERVER_PORT = 9000

        with (
            patch.object(
                mock_chroma, "HttpClient", return_value=mock_client
            ) as mock_http_cls,
            patch.object(rag, "_get_embedding_function", return_value=mock_ef),
        ):
            result = await rag.init_vector_db()

        assert result is True, "init_vector_db should return True in remote mode"

        mock_http_cls.assert_called_once_with(
            host="chroma.example.com",
            port=9000,
        )

        mock_client.get_or_create_collection.assert_called_once_with(
            name="minervini_knowledge",
            embedding_function=mock_ef,
            metadata={"hnsw:space": "cosine"},
        )

    finally:
        config.CHROMA_REMOTE = orig_remote
        config.CHROMA_SERVER_HOST = orig_host
        config.CHROMA_SERVER_PORT = orig_port
        rag._chroma_client = orig_chroma_client
        rag._collection = orig_collection


# ---------------------------------------------------------------------------
# Test 2: Local mode uses PersistentClient (backward compat)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_mode_uses_persistent_client(tmp_path):
    """When CHROMA_REMOTE=false (default), init_vector_db should use
    chromadb.PersistentClient — verifying backward compatibility."""
    import config
    import rag

    mock_collection = _make_mock_collection(doc_count=50)
    mock_client = _make_mock_persistent_client(mock_collection)
    mock_ef = MagicMock()

    # Create a fake knowledge dir with at least one chunk file
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "chunk_001.md").write_text(
        "# Test Chunk\nSome content", encoding="utf-8"
    )

    chroma_dir = tmp_path / "chroma_db"

    orig_remote = getattr(config, "CHROMA_REMOTE", False)
    orig_knowledge = config.KNOWLEDGE_DIR
    orig_chroma_path = config.CHROMA_DB_PATH
    orig_chroma_client = rag._chroma_client
    orig_collection = rag._collection

    try:
        config.CHROMA_REMOTE = False
        config.KNOWLEDGE_DIR = str(knowledge_dir)
        config.CHROMA_DB_PATH = str(chroma_dir)

        with (
            patch.object(
                mock_chroma, "PersistentClient", return_value=mock_client
            ) as mock_persist_cls,
            patch.object(rag, "_get_embedding_function", return_value=mock_ef),
        ):
            result = await rag.init_vector_db()

        assert result is True, "init_vector_db should return True in local mode"

        mock_persist_cls.assert_called_once_with(path=str(chroma_dir))

    finally:
        config.CHROMA_REMOTE = orig_remote
        config.KNOWLEDGE_DIR = orig_knowledge
        config.CHROMA_DB_PATH = orig_chroma_path
        rag._chroma_client = orig_chroma_client
        rag._collection = orig_collection


# ---------------------------------------------------------------------------
# Test 3: Collection properly initialized in remote mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remote_mode_collection_initialized():
    """After init_vector_db in remote mode, the module-level _collection
    should be set to the collection returned by the HttpClient."""
    import config
    import rag

    mock_collection = _make_mock_collection()
    mock_client = _make_mock_http_client(mock_collection)
    mock_ef = MagicMock()

    orig_remote = getattr(config, "CHROMA_REMOTE", False)
    orig_host = getattr(config, "CHROMA_SERVER_HOST", "localhost")
    orig_port = getattr(config, "CHROMA_SERVER_PORT", 8000)
    orig_chroma_client = rag._chroma_client
    orig_collection = rag._collection

    try:
        config.CHROMA_REMOTE = True
        config.CHROMA_SERVER_HOST = "localhost"
        config.CHROMA_SERVER_PORT = 8000

        with (
            patch.object(mock_chroma, "HttpClient", return_value=mock_client),
            patch.object(rag, "_get_embedding_function", return_value=mock_ef),
        ):
            await rag.init_vector_db()

        # Verify _collection is set to the mock collection
        assert rag._collection is mock_collection, (
            "_collection should be set to the collection from HttpClient"
        )
        assert rag._chroma_client is mock_client, (
            "_chroma_client should be set to the HttpClient instance"
        )

    finally:
        config.CHROMA_REMOTE = orig_remote
        config.CHROMA_SERVER_HOST = orig_host
        config.CHROMA_SERVER_PORT = orig_port
        rag._chroma_client = orig_chroma_client
        rag._collection = orig_collection


# ---------------------------------------------------------------------------
# Test 4: query_knowledge works after remote init
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_knowledge_after_remote_init():
    """query_knowledge() should return results after remote init_vector_db."""
    import config
    import rag

    mock_collection = _make_mock_collection()
    mock_client = _make_mock_http_client(mock_collection)
    mock_ef = MagicMock()

    orig_remote = getattr(config, "CHROMA_REMOTE", False)
    orig_host = getattr(config, "CHROMA_SERVER_HOST", "localhost")
    orig_port = getattr(config, "CHROMA_SERVER_PORT", 8000)
    orig_chroma_client = rag._chroma_client
    orig_collection = rag._collection

    try:
        config.CHROMA_REMOTE = True
        config.CHROMA_SERVER_HOST = "localhost"
        config.CHROMA_SERVER_PORT = 8000

        with (
            patch.object(mock_chroma, "HttpClient", return_value=mock_client),
            patch.object(rag, "_get_embedding_function", return_value=mock_ef),
        ):
            await rag.init_vector_db()

        # Now call query_knowledge — it should use the mocked _collection
        results = rag.query_knowledge("VCP breakout pattern", n_results=2)

        assert len(results) == 2, "Should return 2 results"
        assert results[0]["content"] == "Doc about VCP pattern"
        assert results[0]["metadata"]["topic"] == "VCP"
        # cosine similarity = 1 - distance
        assert results[0]["relevance_score"] == round(1 - 0.15, 4)
        assert results[1]["content"] == "Doc about trend template"

        # Verify the collection.query was called
        mock_collection.query.assert_called_once_with(
            query_texts=["VCP breakout pattern"],
            n_results=2,
        )

    finally:
        config.CHROMA_REMOTE = orig_remote
        config.CHROMA_SERVER_HOST = orig_host
        config.CHROMA_SERVER_PORT = orig_port
        rag._chroma_client = orig_chroma_client
        rag._collection = orig_collection


# ---------------------------------------------------------------------------
# Test 5: Remote mode does NOT require knowledge_dir to exist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remote_mode_skips_knowledge_dir_check():
    """In remote mode, init_vector_db should succeed even if KNOWLEDGE_DIR
    does not exist, since the remote server manages storage."""
    import config
    import rag

    mock_collection = _make_mock_collection()
    mock_client = _make_mock_http_client(mock_collection)
    mock_ef = MagicMock()

    orig_remote = getattr(config, "CHROMA_REMOTE", False)
    orig_host = getattr(config, "CHROMA_SERVER_HOST", "localhost")
    orig_port = getattr(config, "CHROMA_SERVER_PORT", 8000)
    orig_knowledge = config.KNOWLEDGE_DIR
    orig_chroma_client = rag._chroma_client
    orig_collection = rag._collection

    try:
        config.CHROMA_REMOTE = True
        config.CHROMA_SERVER_HOST = "localhost"
        config.CHROMA_SERVER_PORT = 8000
        # Set knowledge dir to a path that does NOT exist
        config.KNOWLEDGE_DIR = "/nonexistent/knowledge/dir"

        with (
            patch.object(mock_chroma, "HttpClient", return_value=mock_client),
            patch.object(rag, "_get_embedding_function", return_value=mock_ef),
        ):
            result = await rag.init_vector_db()

        assert result is True, (
            "Remote mode should succeed even if KNOWLEDGE_DIR does not exist"
        )

    finally:
        config.CHROMA_REMOTE = orig_remote
        config.CHROMA_SERVER_HOST = orig_host
        config.CHROMA_SERVER_PORT = orig_port
        config.KNOWLEDGE_DIR = orig_knowledge
        rag._chroma_client = orig_chroma_client
        rag._collection = orig_collection


# ---------------------------------------------------------------------------
# Test 6: Remote mode does NOT create local chroma_db directory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remote_mode_no_local_dir_created(tmp_path):
    """In remote mode, init_vector_db should NOT create a local chroma_db
    directory — the remote server manages its own storage."""
    import config
    import rag

    mock_collection = _make_mock_collection()
    mock_client = _make_mock_http_client(mock_collection)
    mock_ef = MagicMock()

    local_chroma_dir = tmp_path / "should_not_be_created"

    orig_remote = getattr(config, "CHROMA_REMOTE", False)
    orig_host = getattr(config, "CHROMA_SERVER_HOST", "localhost")
    orig_port = getattr(config, "CHROMA_SERVER_PORT", 8000)
    orig_chroma_path = config.CHROMA_DB_PATH
    orig_chroma_client = rag._chroma_client
    orig_collection = rag._collection

    try:
        config.CHROMA_REMOTE = True
        config.CHROMA_SERVER_HOST = "localhost"
        config.CHROMA_SERVER_PORT = 8000
        config.CHROMA_DB_PATH = str(local_chroma_dir)

        with (
            patch.object(mock_chroma, "HttpClient", return_value=mock_client),
            patch.object(rag, "_get_embedding_function", return_value=mock_ef),
        ):
            await rag.init_vector_db()

        assert not local_chroma_dir.exists(), (
            "Remote mode should NOT create local chroma_db directory"
        )

    finally:
        config.CHROMA_REMOTE = orig_remote
        config.CHROMA_SERVER_HOST = orig_host
        config.CHROMA_SERVER_PORT = orig_port
        config.CHROMA_DB_PATH = orig_chroma_path
        rag._chroma_client = orig_chroma_client
        rag._collection = orig_collection


# ---------------------------------------------------------------------------
# Test 7: Config vars have correct defaults
# ---------------------------------------------------------------------------


def test_config_remote_defaults():
    """Verify CHROMA_REMOTE, CHROMA_SERVER_HOST, CHROMA_SERVER_PORT exist
    in config module with sensible defaults."""
    import config

    # CHROMA_REMOTE should default to False (env not set in test conftest)
    assert hasattr(config, "CHROMA_REMOTE"), "config must have CHROMA_REMOTE"
    assert isinstance(config.CHROMA_REMOTE, bool), "CHROMA_REMOTE must be bool"

    assert hasattr(config, "CHROMA_SERVER_HOST"), "config must have CHROMA_SERVER_HOST"
    assert isinstance(config.CHROMA_SERVER_HOST, str), "CHROMA_SERVER_HOST must be str"

    assert hasattr(config, "CHROMA_SERVER_PORT"), "config must have CHROMA_SERVER_PORT"
    assert isinstance(config.CHROMA_SERVER_PORT, int), "CHROMA_SERVER_PORT must be int"


# ---------------------------------------------------------------------------
# Test 8: HttpClient NOT called in local mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_client_not_called_in_local_mode(tmp_path):
    """When CHROMA_REMOTE=false, HttpClient must NOT be instantiated."""
    import config
    import rag

    mock_collection = _make_mock_collection(doc_count=50)
    mock_persist_client = _make_mock_persistent_client(mock_collection)
    mock_ef = MagicMock()

    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "chunk_001.md").write_text("# Test\nContent", encoding="utf-8")

    orig_remote = getattr(config, "CHROMA_REMOTE", False)
    orig_knowledge = config.KNOWLEDGE_DIR
    orig_chroma_path = config.CHROMA_DB_PATH
    orig_chroma_client = rag._chroma_client
    orig_collection = rag._collection

    try:
        config.CHROMA_REMOTE = False
        config.KNOWLEDGE_DIR = str(knowledge_dir)
        config.CHROMA_DB_PATH = str(tmp_path / "chroma_db")

        with (
            patch.object(
                mock_chroma, "PersistentClient", return_value=mock_persist_client
            ),
            patch.object(mock_chroma, "HttpClient") as mock_http_cls,
            patch.object(rag, "_get_embedding_function", return_value=mock_ef),
        ):
            await rag.init_vector_db()

        mock_http_cls.assert_not_called()

    finally:
        config.CHROMA_REMOTE = orig_remote
        config.KNOWLEDGE_DIR = orig_knowledge
        config.CHROMA_DB_PATH = orig_chroma_path
        rag._chroma_client = orig_chroma_client
        rag._collection = orig_collection
