# Requirement R1: Live ChromaDB Integration and Seeding Verification Audit

## 1. Executive Summary
This report provides a read-only investigation and audit of the **R1 Live ChromaDB Integration and Seeding** mechanism in the `TradingViewProject` workspace. 

Our investigation confirms that:
* **Configuration is dynamically resolved** between local path hierarchies and Docker volume mounts, ensuring backward-compatible execution.
* **Seeding is robustly implemented** using a local `SentenceTransformer` model (`paraphrase-multilingual-MiniLM-L12-v2`) which supports multilingual search (including Vietnamese) and computes semantic similarity using Cosine space.
* **Testing validation is complete**: The unit test suite `test_rag_remote.py` passes all 8 test cases validating both local (persistent sqlite) and remote (HTTP client) configurations.
* **Gaps exist**: We have identified key design issues, including:
  1. An unconditional remote connection in the standalone seeding utility (`seed_chroma.py`).
  2. An update cache invalidation limitation in `rag.py`'s automatic seeding check.
  3. A potential crash risk when querying an empty vector collection.

---

## 2. Configuration Resolution (`server/config.py`)

### Path Resolution
The configuration defines three main constants for ChromaDB:
1. `KNOWLEDGE_DIR`: Path to the markdown knowledge base.
2. `CHROMA_DB_PATH`: Persistent storage location for local SQLite/Chroma DB files.
3. `CHROMA_REMOTE`: A boolean flag determining if a remote containerized ChromaDB instance should be used instead of a local disk-based DB.

```python
# server/config.py
default_knowledge_dir = "/app/knowledge/trading_wizard/chunks"
if not os.path.exists(default_knowledge_dir):
    # Local path relative to config.py (server/../docs)
    default_knowledge_dir = str((Path(__file__).resolve().parent.parent / "docs" / "knowledge" / "trading_wizard" / "chunks").absolute())
    if not os.path.exists(default_knowledge_dir):
        # Local path with V9 nested folders (server/../../../../docs)
        default_knowledge_dir = str((Path(__file__).resolve().parent.parent.parent.parent / "docs" / "knowledge" / "trading_wizard" / "chunks").absolute())

KNOWLEDGE_DIR = os.getenv("KNOWLEDGE_DIR", default_knowledge_dir)

CHROMA_DB_PATH = os.getenv(
    "CHROMA_DB_PATH",
    str(Path(__file__).parent / "chroma_db")
)
```

**Observations on Path Resolution**:
* **Local environment**: `default_knowledge_dir` evaluates to `c:\Users\pesil\working\mj_trading\TradingViewProject\docs\knowledge\trading_wizard\chunks` which matches the actual workspace location.
* **Containerized production**: Resolves to `/app/knowledge/trading_wizard/chunks` via the environment variable `KNOWLEDGE_DIR` loaded from `.env.production`.
* **Chroma DB path**: Resolves locally to `server/chroma_db` (containing `chroma.sqlite3`, ~3.9 MB).

### Connection Type Resolution
ChromaDB client initialization uses the `CHROMA_REMOTE` environment variable:
* `CHROMA_REMOTE = True` $\rightarrow$ Connect via HTTP client using `CHROMA_SERVER_HOST` (default: `"localhost"`) and `CHROMA_SERVER_PORT` (default: `8000`).
* `CHROMA_REMOTE = False` $\rightarrow$ Connect locally using SQLite-backed `PersistentClient`.

---

## 3. Seeding Process (`server/scripts/seed_chroma.py`)

### Chunk Ingestion & Parsing
The seeding script locates knowledge chunk files named `chunk_*.md` within `config.KNOWLEDGE_DIR`. The parsing logic performs the following steps:
1. **File discovery**: Reads and sorts all chunk filenames.
2. **Title metadata**: Searches the document for the first header starting with `# ` to assign as the `topic` metadata value.
3. **Chapter metadata**: Uses regex `r"chunk_(\d+)"` to extract chapter indices from the filename.
4. **Document IDs**: Constructs document IDs in the format `minervini_{chunk_file.stem}` (e.g., `minervini_chunk_001`).

```python
meta = {"filename": chunk_file.name, "topic": "general", "chapter": ""}
lines = content.strip().splitlines()
for line in lines:
    if line.startswith("# "):
        meta["topic"] = line.lstrip("# ").strip()
        break
match = re.search(r"chunk_(\d+)", chunk_file.name)
if match:
    meta["chapter"] = match.group(1)
```

### Embedding & Uploads
* **Embedding Model**: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.
* **Batch Size**: Documents are uploaded in batches of 10 (`batch_size = 10`) using `collection.upsert()`, which replaces documents with duplicate IDs or inserts them otherwise.
* **Remote-Only Bias Gap**:
  The seeding script `server/scripts/seed_chroma.py` has an integration bug/limitation. It ignores `config.CHROMA_REMOTE` and unconditionally instantiates `chromadb.HttpClient`:
  ```python
  # Resolve ChromaDB connection (favoring remote configuration for this script)
  host = os.getenv("CHROMA_SERVER_HOST", config.CHROMA_SERVER_HOST)
  port = int(os.getenv("CHROMA_SERVER_PORT", config.CHROMA_SERVER_PORT))
  
  logger.info(f"Connecting to ChromaDB at http://{host}:{port}...")
  client = chromadb.HttpClient(host=host, port=port)
  ```
  If a developer executes `seed_chroma.py` in a local setup where `CHROMA_REMOTE=false` (using SQLite local DB), the script will crash because it attempts to reach a non-existent HTTP ChromaDB server.

---

## 4. Collection Retrieval (`server/rag.py`)

### Initialization Flow
During application startup (FastAPI lifespan), `init_vector_db()` is called:
1. Initializes `_chroma_client` (using either `PersistentClient` or `HttpClient` based on config).
2. Sets up `_collection` named `"minervini_knowledge"` with Cosine distance metric:
   ```python
   _collection = _chroma_client.get_or_create_collection(
       name="minervini_knowledge",
       embedding_function=ef,
       metadata={"hnsw:space": "cosine"},
   )
   ```
3. Checks if the collection has already been seeded by comparing the document count:
   ```python
   existing_count = _collection.count()
   if existing_count >= len(chunk_files):
       log.info(f"RAG: Vector DB đã có {existing_count} vectors. Bỏ qua re-embedding.")
       return True
   ```
4. If empty or missing, it reads the markdown chunk files, embeds them, and batch-upserts them.

### Query Construction & Retrieval
When a TradingView webhook signal arrives:
1. **Semantic Query Construction**: `build_rag_query` constructs a query based on signal metrics (e.g. VCP detection, Trend Template status, or volume spikes).
2. **Retrieval**:
   ```python
   results = _collection.query(
       query_texts=[query],
       n_results=min(n_results, _collection.count()),
   )
   ```
3. **Similarity Score Calculation**: ChromaDB's Cosine distance is converted back to cosine similarity score using:
   `relevance_score = round(1 - distance, 4)`
4. **Context Injection**: The top $K$ relevant chunks are embedded in the prompt and passed to the AI model (Claude/Gemini) to approve/reject the transaction.

---

## 5. Verification Results

### Unit Tests
The test file `nerves/workers/trading/tests/test_rag_remote.py` covers:
* `test_remote_mode_uses_http_client` (PASSED)
* `test_local_mode_uses_persistent_client` (PASSED)
* `test_remote_mode_collection_initialized` (PASSED)
* `test_query_knowledge_after_remote_init` (PASSED)
* `test_remote_mode_skips_knowledge_dir_check` (PASSED)
* `test_remote_mode_no_local_dir_created` (PASSED)
* `test_config_remote_defaults` (PASSED)
* `test_http_client_not_called_in_local_mode` (PASSED)

### Diagnostic Script Run
Running `verify_rag.py` confirmed that:
* The system is currently in local mode (`CHROMA_REMOTE=false`).
* ChromaDB loads the cached Hugging Face model files (`paraphrase-multilingual-MiniLM-L12-v2`) locally and initializes PyTorch/transformers correctly.
* The local SQLite DB file `server/chroma_db/chroma.sqlite3` exists and has a size of 3,899,392 bytes.

---

## 6. Identified Gaps, Bugs & Risks

### [BUG-001] Standalone Seeding Tool ignores `CHROMA_REMOTE`
* **File**: `server/scripts/seed_chroma.py` (lines 38-43)
* **Risk**: High for local testing. Running this script locally fails because it unconditionally uses `chromadb.HttpClient(host=host, port=port)` rather than checking `config.CHROMA_REMOTE` to fall back to `PersistentClient(path=...)`.
* **Fix Proposal**: Update the script connection logic to match `rag.py`:
  ```python
  if getattr(config, "CHROMA_REMOTE", False):
      client = chromadb.HttpClient(host=host, port=port)
  else:
      client = chromadb.PersistentClient(path=config.CHROMA_DB_PATH)
  ```

### [BUG-002] RAG Query Zero-Count Crash Risk
* **File**: `server/rag.py` (lines 276-279)
* **Risk**: Medium. In `query_knowledge`, the system queries `n_results=min(n_results, _collection.count())`. If `_collection.count()` is 0, this calls `_collection.query` with `n_results=0`. Some versions of ChromaDB throw a `ValueError` for `n_results=0`. Although wrapped in `try...except`, this blocks successful execution.
* **Fix Proposal**: Add an early exit condition:
  ```python
  if _collection is None or _collection.count() == 0:
      return []
  ```

### [BUG-003] Update Caching Policy Gap (LLM Stale Data Risk)
* **File**: `server/rag.py` (lines 221-226)
* **Risk**: Low-Medium. The auto-seeding logic checks: `if existing_count >= len(chunk_files): return True`. If a developer edits a markdown chunk on disk, the database count does not change, meaning the modified content is **never** re-embedded or updated.
* **Fix Proposal**: Provide a manual override flag in config or check file modification times to force re-seeding if needed.
