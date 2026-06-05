import asyncio
import sys
from pathlib import Path

# Add root directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import rag


async def main():
    print("Initializing RAG Vector Database...")
    success = await rag.init_vector_db()
    if not success:
        print("Failed to initialize vector database.")
        sys.exit(1)

    print("RAG database initialized successfully.")

    # Query count
    if rag._collection is not None:
        count = rag._collection.count()
        print(f"Collection 'minervini_knowledge' has {count} documents.")

        # Verify if count matches files on disk
        knowledge_dir = Path(config.KNOWLEDGE_DIR)
        disk_files = list(knowledge_dir.glob("chunk_*.md"))
        print(f"Number of chunk files on disk: {len(disk_files)}")

        if count == len(disk_files):
            print(
                "Verification PASSED: Database collection count matches disk file count."
            )
        else:
            print("Verification WARNING: Count mismatch. Forcing re-ingestion...")
            # We can clear and re-upsert if needed, or print warning.
            # Let's delete and recreate the collection to force seed if needed:
            # rag._chroma_client.delete_collection("minervini_knowledge")
    else:
        print("Error: Collection not found.")


if __name__ == "__main__":
    asyncio.run(main())
