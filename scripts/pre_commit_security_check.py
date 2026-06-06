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
        f"[Pre-commit Security] Staged Python files detected ({len(py_files)} files). Running checks..."
    )

    # 1. Run ruff check on staged files
    print("[Pre-commit Security] Running Ruff check on staged files...")
    ruff_cmd = ["ruff", "check"] + py_files
    res_ruff = subprocess.run(
        ruff_cmd, capture_output=True, text=True, encoding="utf-8"
    )
    if res_ruff.returncode != 0:
        print("\n❌ [Pre-commit Security] Ruff check failed!\n", file=sys.stderr)
        print(res_ruff.stdout)
        print(res_ruff.stderr, file=sys.stderr)
        sys.exit(res_ruff.returncode)

    # 2. Run ruff format --check on staged files
    print("[Pre-commit Security] Running Ruff format check on staged files...")
    fmt_cmd = ["ruff", "format", "--check"] + py_files
    res_fmt = subprocess.run(fmt_cmd, capture_output=True, text=True, encoding="utf-8")
    if res_fmt.returncode != 0:
        print("\n❌ [Pre-commit Security] Ruff format check failed!\n", file=sys.stderr)
        print(res_fmt.stdout)
        print(res_fmt.stderr, file=sys.stderr)
        sys.exit(res_fmt.returncode)

    # 3. Run Mini-MDASH scan on staged files
    print("[Pre-commit Security] Running Mini-MDASH security scan on staged files...")
    repo_root = os.getcwd()
    server_dir = os.path.join(repo_root, "server")

    # Run security.cli from the server folder (if it exists) to scan, format as json
    cwd = server_dir if os.path.exists(server_dir) else repo_root
    target = "."  # Since we are running in the target directory (server)

    cmd = [
        sys.executable,
        "-m",
        "security.cli",
        "scan",
        "--format",
        "json",
        "--target",
        target,
    ]

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

        if process.returncode != 0 and not process.stdout:
            print(
                "❌ [Pre-commit Security] Scanner command failed to execute:",
                file=sys.stderr,
            )
            print(process.stderr, file=sys.stderr)
            sys.exit(1)

        import json

        try:
            report_data = json.loads(process.stdout)
            findings = report_data.get("findings", [])
        except json.JSONDecodeError as e:
            print(
                f"❌ [Pre-commit Security] Failed to parse scanner output: {e}",
                file=sys.stderr,
            )
            print("Output was:", file=sys.stderr)
            print(process.stdout, file=sys.stderr)
            print(process.stderr, file=sys.stderr)
            sys.exit(1)

        # Filter findings that correspond to the staged python files.
        # staged files in py_files are relative to repo root (e.g. server/config.py)
        # findings files might be relative to server_dir or absolute.
        # Let's resolve both to absolute paths for robust comparison.
        staged_abs_paths = {os.path.abspath(f) for f in py_files}

        failing_findings = []
        for f in findings:
            severity = f.get("severity", "").lower()
            if severity in ("critical", "high"):
                # The file path in finding could be relative to cwd (server) or absolute.
                f_file = f.get("file", "")
                f_abs_path = os.path.abspath(os.path.join(cwd, f_file))
                if f_abs_path in staged_abs_paths:
                    failing_findings.append(f)

        if failing_findings:
            print(
                f"\n❌ [Pre-commit Security] SCAN FAILED: {len(failing_findings)} HIGH/CRITICAL security issues found in staged files!\n",
                file=sys.stderr,
            )
            for f in failing_findings:
                f_file = f.get("file", "")
                f_abs_path = os.path.abspath(os.path.join(cwd, f_file))
                rel_path = os.path.relpath(f_abs_path, repo_root)
                print(
                    f"  [{f.get('rule_id', '?')}] {f.get('severity', '').upper()} in {rel_path}:line {f.get('line', '?')} — {f.get('title', '?')}",
                    file=sys.stderr,
                )
                print(
                    f"      Description: {f.get('description', '?')}", file=sys.stderr
                )
                if f.get("evidence"):
                    print(f"      Evidence: {f.get('evidence', '')}", file=sys.stderr)
            print(
                "\n⚠️ Commit blocked. Please resolve the security findings above or use git commit --no-verify if intentional.",
                file=sys.stderr,
            )
            sys.exit(1)
        else:
            print(
                "[Pre-commit Security] SCAN PASSED: No HIGH/CRITICAL security issues found in staged files."
            )
            sys.exit(0)

    except Exception as e:
        print(f"❌ Error running security scanner: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
