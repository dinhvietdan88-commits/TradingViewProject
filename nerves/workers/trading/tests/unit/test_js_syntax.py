import subprocess
from pathlib import Path
import pytest


def test_javascript_syntax():
    """Scan all JavaScript files in the static directory and verify syntax using node -c."""
    server_dir = Path(__file__).resolve().parent.parent.parent
    js_dir = server_dir / "static" / "js"

    assert js_dir.exists(), f"Static JS directory not found: {js_dir}"

    js_files = list(js_dir.glob("**/*.js"))
    assert len(js_files) > 0, "No JavaScript files found to check!"

    errors = []
    for file_path in js_files:
        # Run node -c (syntax check) on the file
        res = subprocess.run(
            ["node", "-c", str(file_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if res.returncode != 0:
            errors.append(f"Syntax error in {file_path.name}:\n{res.stderr.strip()}")

    if errors:
        pytest.fail("\n\n".join(errors))
