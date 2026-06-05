import fitz
import os
import re

PDF_PATH = r"c:\Users\Son\OneDrive\Tài liệu\Bussiness\MJ\Trading\TradingViewProject\docs\references\Unlock_Trade_Like_a_Stock_Market_Wizard_How_to_Achieve_Super_Performance.pdf"
OUTPUT_DIR = r"c:\Users\Son\OneDrive\Tài liệu\Bussiness\MJ\Trading\TradingViewProject\docs\knowledge\trading_wizard"
CHUNKS_DIR = os.path.join(OUTPUT_DIR, "chunks")

os.makedirs(CHUNKS_DIR, exist_ok=True)

doc = fitz.open(PDF_PATH)
PAGES_PER_CHUNK = 10
total_pages = len(doc)
chunks = []


def clean_text(text):
    # Basic cleanup: remove excessive newlines
    text = re.sub(r"\n+", "\n", text)
    return text


current_chunk_text = ""
chunk_index = 1
start_page = 1

for i in range(total_pages):
    page = doc.load_page(i)
    text = page.get_text("text")
    if text:
        current_chunk_text += f"\n\n## Page {i + 1}\n\n" + clean_text(text)

    if (i + 1) % PAGES_PER_CHUNK == 0 or (i + 1) == total_pages:
        end_page = i + 1
        chunk_filename = f"chunk_{chunk_index:03d}.md"
        chunk_path = os.path.join(CHUNKS_DIR, chunk_filename)

        with open(chunk_path, "w", encoding="utf-8") as f:
            f.write(
                f"# Unlock Trade Like a Stock Market Wizard - Pages {start_page} to {end_page}\n"
            )
            f.write(current_chunk_text)

        chunks.append(
            {
                "filename": chunk_filename,
                "title": f"Pages {start_page} to {end_page}",
                "start": start_page,
                "end": end_page,
            }
        )

        current_chunk_text = ""
        chunk_index += 1
        start_page = i + 2

# Create index.md
index_path = os.path.join(OUTPUT_DIR, "index.md")
with open(index_path, "w", encoding="utf-8") as f:
    f.write("# Knowledge Base: Unlock Trade Like a Stock Market Wizard\n\n")
    f.write(
        "This directory contains the chunked knowledge from the book for RAG and Agents.\n\n"
    )
    f.write("## Index of Chunks\n\n")
    for chunk in chunks:
        f.write(f"- [{chunk['title']}](chunks/{chunk['filename']})\n")

print(
    f"Extraction complete! Generated {len(chunks)} chunks. Total pages: {total_pages}"
)
