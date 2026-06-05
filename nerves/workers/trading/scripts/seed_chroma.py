import logging
import os
from pathlib import Path
import re
import sys

from dotenv import load_dotenv

# Add server directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb
import config
from chromadb.utils import embedding_functions

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("seed_chroma")

# Resolve server directory for env load
server_dir = Path(__file__).resolve().parent.parent

# Attempt to load env from deploy/.env first, then default .env
deploy_env = server_dir.parent / "deploy" / ".env"
if deploy_env.exists():
    logger.info(f"Loading env from {deploy_env}")
    load_dotenv(deploy_env)
else:
    local_env = server_dir / ".env"
    if local_env.exists():
        logger.info(f"Loading env from {local_env}")
        load_dotenv(local_env)
    else:
        logger.info("No specific .env files found, using system environment variables")


def main():
    # Resolve ChromaDB connection
    if getattr(config, "CHROMA_REMOTE", False):
        host = os.getenv("CHROMA_SERVER_HOST", config.CHROMA_SERVER_HOST)
        port = int(os.getenv("CHROMA_SERVER_PORT", config.CHROMA_SERVER_PORT))
        logger.info(f"Connecting to remote ChromaDB at http://{host}:{port}...")
        client = chromadb.HttpClient(host=host, port=port)
    else:
        path = getattr(config, "CHROMA_DB_PATH", "chroma_db")
        logger.info(
            f"Connecting to local ChromaDB persistent client at path: {path}..."
        )
        client = chromadb.PersistentClient(path=str(path))

    # Embedding function
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="paraphrase-multilingual-MiniLM-L12-v2"
    )

    collection = client.get_or_create_collection(
        name="minervini_knowledge",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    # Resolve knowledge directory
    knowledge_dir = Path(config.KNOWLEDGE_DIR)
    if not knowledge_dir.exists():
        logger.error(f"Knowledge directory not found at: {knowledge_dir}")
        sys.exit(1)

    chunk_files = sorted(knowledge_dir.glob("chunk_*.md"))
    if not chunk_files:
        logger.warning(f"No chunk files (chunk_*.md) found in {knowledge_dir}")
        sys.exit(0)

    logger.info(f"Found {len(chunk_files)} knowledge chunks in {knowledge_dir}")

    documents, metadatas, ids = [], [], []
    for chunk_file in chunk_files:
        try:
            content = chunk_file.read_text(encoding="utf-8")
            if not content.strip():
                continue

            # Simple parse metadata
            meta = {"filename": chunk_file.name, "topic": "general", "chapter": ""}
            lines = content.strip().splitlines()
            for line in lines:
                if line.startswith("# "):
                    meta["topic"] = line.lstrip("# ").strip()
                    break
            match = re.search(r"chunk_(\d+)", chunk_file.name)
            if match:
                meta["chapter"] = match.group(1)

            doc_id = f"minervini_{chunk_file.stem}"

            documents.append(content)
            metadatas.append(meta)
            ids.append(doc_id)
        except Exception as e:
            logger.warning(f"Error reading {chunk_file.name}: {e}")

    if documents:
        logger.info(
            f"Upserting {len(documents)} chunks to remote collection 'minervini_knowledge'..."
        )
        batch_size = 10
        for i in range(0, len(documents), batch_size):
            collection.upsert(
                documents=documents[i : i + batch_size],
                metadatas=metadatas[i : i + batch_size],
                ids=ids[i : i + batch_size],
            )
            logger.info(
                f"Progress: {min(i + batch_size, len(documents))}/{len(documents)} chunks uploaded."
            )

        logger.info("✅ ChromaDB knowledge seeding completed successfully!")
        logger.info(f"Remote collection count: {collection.count()} vectors.")
    else:
        logger.warning("No valid documents to upsert.")


if __name__ == "__main__":
    main()
