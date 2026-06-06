import re
from pathlib import Path


def main():
    base_dir = Path(__file__).parent.parent
    knowledge_dir = base_dir / "docs" / "knowledge" / "trading_wizard"
    chunks_dir = knowledge_dir / "chunks"

    # Ensure chunks dir exists
    chunks_dir.mkdir(parents=True, exist_ok=True)

    mindmaps_file = knowledge_dir / "minervini_mindmaps.md"
    if not mindmaps_file.exists():
        print(f"File not found: {mindmaps_file}")
        return

    content = mindmaps_file.read_text(encoding="utf-8")

    # Split by '## ' to get the different sections
    sections = re.split(r"\n## ", content)

    # First section is the intro, skip it or combine it
    sections[0]

    for i, section in enumerate(sections[1:], 1):
        # The section content will have the title on the first line
        chunk_content = f"# {section.strip()}"

        # Determine a topic name from the first line
        first_line = section.split("\n")[0].strip()
        safe_name = "".join(c if c.isalnum() else "_" for c in first_line)

        chunk_filename = chunks_dir / f"chunk_{i:03d}_{safe_name}.md"
        chunk_filename.write_text(chunk_content, encoding="utf-8")
        print(f"Created {chunk_filename.name}")


if __name__ == "__main__":
    main()
