#!/usr/bin/env python3
"""
Setup script to configure local Git pre-commit hooks.
"""

import io
import os
import stat
import sys


def install_pre_commit_hook():
    # Force UTF-8 encoding for stdout/stderr to prevent Windows charmap exceptions
    if sys.stdout and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
    if sys.stderr and hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace"
        )

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    git_hooks_dir = os.path.join(repo_root, ".git", "hooks")

    if not os.path.exists(git_hooks_dir):
        print(
            f"Error: .git/hooks directory not found at {git_hooks_dir}. Make sure you are in a git repository.",
            file=sys.stderr,
        )
        sys.exit(1)

    pre_commit_path = os.path.join(git_hooks_dir, "pre-commit")

    # Shell script wrapper that calls python
    # This works in Git Bash/WSL on Windows as well as macOS/Linux
    hook_content = """#!/bin/sh
# Antigravity IDE Auto-Generated Pre-Commit Security Hook
python scripts/pre_commit_security_check.py
"""

    try:
        with open(pre_commit_path, "w", newline="\n", encoding="utf-8") as f:
            f.write(hook_content)

        # Make it executable (unix permissions)
        st = os.stat(pre_commit_path)
        os.chmod(pre_commit_path, st.st_mode | stat.S_IEXEC)

        print(
            f"[Pre-commit Security] Pre-commit security hook successfully installed at: {pre_commit_path}"
        )
        print(
            "Hook will run automatically on 'git commit' whenever Python files are modified."
        )
    except Exception as e:
        print(f"Error installing hook: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    install_pre_commit_hook()
