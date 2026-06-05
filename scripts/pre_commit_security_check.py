#!/usr/bin/env python3
"""
Git Pre-commit Hook for Security Scanning.
Runs the Mini-MDASH security scanner on changed Python files.
"""

import io
import os
import subprocess
import sys


def get_staged_python_files():
    """Get a list of currently staged Python files."""
    try:
        output = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only"], text=True
        )
        files = [line.strip() for line in output.split("\n") if line.strip()]
        # Filter for Python files, excluding test files and virtual environments
        py_files = [
            f
            for f in files
            if f.endswith(".py")
            and not f.startswith("tests/")
            and not f.startswith("server/tests/")
            and "test_" not in os.path.basename(f)
            and ".venv/" not in f
            and "venv/" not in f
        ]
        return py_files
    except subprocess.CalledProcessError as e:
        print(f"Error running git diff: {e}", file=sys.stderr)
        return []


def main():
    # Force UTF-8 encoding for stdout/stderr to prevent Windows charmap exceptions
    if sys.stdout and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
    if sys.stderr and hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace"
        )

    py_files = get_staged_python_files()
    if not py_files:
        print(
            "[Pre-commit Security] No staged Python code changes detected. Skipping scan."
        )
        sys.exit(0)

    print(
        f"[Pre-commit Security] Staged Python files detected ({len(py_files)} files). Running security scan..."
    )

    # Determine paths
    repo_root = os.getcwd()
    server_dir = os.path.join(repo_root, "server")

    # We want to run: python -m security.cli scan --ci --fail-on high
    cmd = [sys.executable, "-m", "security.cli", "scan", "--ci", "--fail-on", "high"]

    # Run from the server folder if it exists, otherwise from repo root
    cwd = server_dir if os.path.exists(server_dir) else repo_root

    try:
        # Run the security scanner CLI
        process = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

        if process.returncode != 0:
            print(
                "\n❌ [Pre-commit Security] SCAN FAILED: Security issues found or scan errored!\n",
                file=sys.stderr,
            )
            print(process.stdout)
            print(process.stderr, file=sys.stderr)
            print(
                "\n⚠️ Commit blocked. Please resolve the security findings above or use git commit --no-verify if intentional.",
                file=sys.stderr,
            )
            sys.exit(1)
        else:
            print(
                "[Pre-commit Security] SCAN PASSED: No HIGH/CRITICAL security issues found."
            )
            sys.exit(0)

    except Exception as e:
        print(f"❌ Error running security scanner: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
