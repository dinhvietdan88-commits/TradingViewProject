#!/usr/bin/env python3
"""
sec-02: Local Dev Security Gate — Unified local quality & security scanner.

Combines: pre-commit hooks + Ruff lint + Mini-MDASH + CodeQL CLI (optional)
into a single command-line tool for local development validation.

Usage:
    python scripts/local_security_gate.py check          # Full check (lint + security)
    python scripts/local_security_gate.py check --quick   # Quick: lint only
    python scripts/local_security_gate.py check --deep    # Deep: + CodeQL analysis
    python scripts/local_security_gate.py setup           # First-time setup
    python scripts/local_security_gate.py status          # Show gate readiness
"""

import argparse
import io
import os
import shutil
import subprocess
import sys
import time

# ── UTF-8 stdout for Windows ────────────────────────────────────────
if sys.stdout and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ── Constants ───────────────────────────────────────────────────────
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(REPO_ROOT, "server")
CODEQL_DIR = os.path.join(REPO_ROOT, ".codeql")
CODEQL_DB = os.path.join(CODEQL_DIR, "db-python")


def _run(cmd, cwd=None, check=False, capture=True, timeout=300):
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd,
            cwd=cwd or REPO_ROOT,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
        return r.returncode, r.stdout or "", r.stderr or ""
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", f"Command timed out after 300s: {' '.join(cmd)}"


def _has_cmd(name):
    """Check if a command is available on PATH."""
    return shutil.which(name) is not None


def _print_header(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def _print_result(name, passed, detail=""):
    icon = "PASS" if passed else "FAIL"
    emoji = "\u2705" if passed else "\u274c"
    line = f"  {emoji} [{icon}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return passed


# ═════════════════════════════════════════════════════════════════════
# GATE 1: Ruff Lint
# ═════════════════════════════════════════════════════════════════════
def gate_ruff_lint(files=None):
    """Run Ruff lint check on server/ or specific files."""
    _print_header("Gate 1: Ruff Lint (E/W/F/S/B)")

    ruff_cmd = "ruff"
    if not _has_cmd(ruff_cmd):
        return _print_result("Ruff Lint", False, "ruff not found — pip install ruff")

    targets = files if files else ["server/"]
    rc, out, err = _run(
        [ruff_cmd, "check", "--statistics"] + targets,
    )

    combined = out + "\n" + err

    if rc == 0:
        return _print_result("Ruff Lint", True, "0 errors")
    else:
        # Parse "Found N errors." from output
        total = 0
        for line in combined.split("\n"):
            if line.strip().startswith("Found ") and "error" in line:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1].isdigit():
                    total = int(parts[1])

        # Show top 10 stat lines (tab-separated: count\trule\t[fix]\tdescription)
        stats = [
            line.strip()
            for line in combined.split("\n")
            if line.strip() and "\t" in line
        ]
        for s in stats[:10]:
            print(f"    {s}")

        return _print_result("Ruff Lint", False, f"{total} errors found")


# ═════════════════════════════════════════════════════════════════════
# GATE 2: Ruff Format Check
# ═════════════════════════════════════════════════════════════════════
def gate_ruff_format(files=None):
    """Check if code is properly formatted."""
    _print_header("Gate 2: Ruff Format Check")

    if not _has_cmd("ruff"):
        return _print_result("Ruff Format", False, "ruff not found")

    targets = files if files else ["server/"]
    rc, out, err = _run(
        ["ruff", "format", "--check", "--diff"] + targets,
    )

    if rc == 0:
        return _print_result("Ruff Format", True, "all files formatted")
    else:
        # Count files that would be reformatted
        diff_files = [
            line
            for line in out.split("\n")
            if line.startswith("Would reformat") or line.startswith("---")
        ]
        return _print_result(
            "Ruff Format",
            False,
            f"{len(diff_files)} files need formatting — run: ruff format server/",
        )


# ═════════════════════════════════════════════════════════════════════
# GATE 3: Mini-MDASH Security Scan
# ═════════════════════════════════════════════════════════════════════
def gate_security_scan():
    """Run the Mini-MDASH / Angati Internal Security Scanner."""
    _print_header("Gate 3: Mini-MDASH Security Scan")

    cwd = SERVER_DIR if os.path.isdir(SERVER_DIR) else REPO_ROOT
    rc, out, err = _run(
        [sys.executable, "-m", "security.cli", "scan", "--ci", "--fail-on", "high"],
        cwd=cwd,
    )

    if rc == 0:
        return _print_result("Security Scan", True, "0 HIGH/CRITICAL findings")
    elif rc == -1:
        return _print_result("Security Scan", True, "scanner not available (skipped)")
    else:
        # Parse findings count
        for line in (out + err).split("\n"):
            if "finding" in line.lower():
                print(f"    {line.strip()}")
        return _print_result("Security Scan", False, "HIGH/CRITICAL findings detected")


# ═════════════════════════════════════════════════════════════════════
# GATE 4: CodeQL Local Analysis (--deep mode)
# ═════════════════════════════════════════════════════════════════════
def gate_codeql():
    """Run CodeQL local analysis (requires codeql CLI installed)."""
    _print_header("Gate 4: CodeQL Local Analysis (Deep)")

    if not _has_cmd("codeql"):
        return _print_result(
            "CodeQL",
            True,
            "CodeQL CLI not installed (skipped) — run: local_security_gate.py setup",
        )

    print("  Creating CodeQL database (this may take 1-2 minutes)...")
    start = time.time()

    # Ensure .codeql directory exists
    os.makedirs(CODEQL_DIR, exist_ok=True)

    # Create/update database
    rc, out, err = _run(
        [
            "codeql",
            "database",
            "create",
            CODEQL_DB,
            "--language=python",
            "--source-root",
            REPO_ROOT,
            "--overwrite",
        ],
        timeout=600,
    )

    if rc != 0:
        print(f"    stderr: {err[:200]}")
        return _print_result("CodeQL DB Create", False, f"exit code {rc}")

    elapsed_db = time.time() - start
    print(f"  Database created in {elapsed_db:.1f}s")

    # Analyze
    print("  Running CodeQL analysis...")
    start = time.time()
    rc, out, err = _run(
        [
            "codeql",
            "database",
            "analyze",
            CODEQL_DB,
            "--format=sarif-latest",
            "--output",
            os.path.join(CODEQL_DIR, "results.sarif"),
            "--",
            "codeql/python-queries",
        ],
        timeout=600,
    )

    elapsed_analyze = time.time() - start
    print(f"  Analysis completed in {elapsed_analyze:.1f}s")

    if rc != 0:
        print(f"    stderr: {err[:200]}")
        return _print_result("CodeQL Analysis", False, f"exit code {rc}")

    # Parse SARIF for results
    try:
        import json

        sarif_path = os.path.join(CODEQL_DIR, "results.sarif")
        with open(sarif_path, encoding="utf-8") as f:
            sarif = json.load(f)
        results = []
        for run in sarif.get("runs", []):
            results.extend(run.get("results", []))

        high_count = sum(1 for r in results if r.get("level") in ("error", "warning"))
        if high_count == 0:
            return _print_result(
                "CodeQL Analysis",
                True,
                f"0 issues ({len(results)} total, {elapsed_analyze:.0f}s)",
            )
        else:
            # Show top findings
            for r in results[:5]:
                rule = r.get("ruleId", "?")
                msg = r.get("message", {}).get("text", "")[:80]
                loc = r.get("locations", [{}])[0]
                path = (
                    loc.get("physicalLocation", {})
                    .get("artifactLocation", {})
                    .get("uri", "?")
                )
                print(f"    {rule}: {path} — {msg}")
            return _print_result("CodeQL Analysis", False, f"{high_count} issues found")
    except Exception as e:
        return _print_result("CodeQL Parse", False, str(e))


# ═════════════════════════════════════════════════════════════════════
# GATE 5: Pre-commit Check
# ═════════════════════════════════════════════════════════════════════
def gate_precommit():
    """Verify pre-commit hooks are installed."""
    _print_header("Gate 5: Pre-commit Hooks")

    hook_path = os.path.join(REPO_ROOT, ".git", "hooks", "pre-commit")
    has_hook = os.path.exists(hook_path)

    if has_hook:
        # Check if it's the pre-commit framework hook
        with open(hook_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        is_framework = "pre-commit" in content.lower()
        if is_framework:
            return _print_result("Pre-commit Hooks", True, "installed and active")
        else:
            return _print_result(
                "Pre-commit Hooks",
                True,
                "legacy hook found (pre-commit framework available as .legacy)",
            )
    else:
        return _print_result(
            "Pre-commit Hooks", False, "not installed — run: pre-commit install"
        )


# ═════════════════════════════════════════════════════════════════════
# COMMANDS
# ═════════════════════════════════════════════════════════════════════
def cmd_check(args):
    """Run quality gate checks."""
    _print_header("sec-02: Local Dev Security Gate")
    print(f"  Mode: {'quick' if args.quick else 'deep' if args.deep else 'standard'}")
    print(f"  Repo: {REPO_ROOT}")
    if args.files:
        print(f"  Files: {', '.join(args.files)}")

    results = []
    start = time.time()

    # Always run: lint + format + pre-commit status
    results.append(("Ruff Lint", gate_ruff_lint(args.files)))
    results.append(("Ruff Format", gate_ruff_format(args.files)))
    results.append(("Pre-commit", gate_precommit()))

    if not args.quick:
        # Standard: + security scan
        results.append(("Security", gate_security_scan()))

    if args.deep:
        # Deep: + CodeQL
        results.append(("CodeQL", gate_codeql()))

    elapsed = time.time() - start

    # Summary
    _print_header("SUMMARY")
    passed = sum(1 for _, r in results if r)
    total = len(results)
    all_pass = passed == total

    for name, r in results:
        icon = "\u2705" if r else "\u274c"
        print(f"  {icon} {name}")

    print(f"\n  Result: {passed}/{total} gates passed ({elapsed:.1f}s)")

    if all_pass:
        print("\n  \U0001f3c6 ALL GATES PASSED — Ready to commit")
    else:
        print("\n  \u26a0\ufe0f GATES FAILED — Fix issues before committing")

    return 0 if all_pass else 1


def cmd_setup(args):
    """First-time setup: install pre-commit, check ruff, check CodeQL."""
    _print_header("sec-02: Setup Local Dev Security Gate")

    # 1. Check ruff
    print("  [1/4] Checking ruff...")
    if _has_cmd("ruff"):
        rc, out, _ = _run(["ruff", "--version"])
        print(f"    \u2705 ruff {out.strip()}")
    else:
        print("    \u274c ruff not found — installing...")
        _run([sys.executable, "-m", "pip", "install", "ruff"])

    # 2. Check pre-commit
    print("  [2/4] Checking pre-commit...")
    if _has_cmd("pre-commit"):
        rc, out, _ = _run(["pre-commit", "--version"])
        print(f"    \u2705 {out.strip()}")
        # Install hooks
        rc, out, err = _run(["pre-commit", "install"])
        if rc == 0:
            print(f"    \u2705 Hooks installed: {out.strip()}")
        else:
            print(f"    \u26a0\ufe0f Hook install issue: {(err or out).strip()}")
    else:
        print("    \u274c pre-commit not found — run: pip install pre-commit")

    # 3. Check CodeQL
    print("  [3/4] Checking CodeQL CLI...")
    if _has_cmd("codeql"):
        rc, out, _ = _run(["codeql", "--version"])
        print(f"    \u2705 codeql {out.strip().split(chr(10))[0]}")
    else:
        print("    \u26a0\ufe0f CodeQL CLI not installed (optional)")
        print(
            "    \u2139\ufe0f  Download: https://github.com/github/codeql-cli-binaries/releases"
        )
        print("    \u2139\ufe0f  Extract to C:\\CodeQL and add to PATH")

    # 4. Check pyproject.toml
    print("  [4/4] Checking pyproject.toml (ruff config)...")
    toml_path = os.path.join(REPO_ROOT, "pyproject.toml")
    if os.path.exists(toml_path):
        print(f"    \u2705 {toml_path}")
    else:
        print(f"    \u274c pyproject.toml not found at {REPO_ROOT}")

    print("\n  Setup complete. Run: python scripts/local_security_gate.py check")
    return 0


def cmd_status(args):
    """Show gate readiness status."""
    _print_header("sec-02: Gate Readiness Status")

    tools = {
        "ruff": _has_cmd("ruff"),
        "pre-commit": _has_cmd("pre-commit"),
        "codeql": _has_cmd("codeql"),
    }

    files = {
        "pyproject.toml": os.path.exists(os.path.join(REPO_ROOT, "pyproject.toml")),
        ".pre-commit-config.yaml": os.path.exists(
            os.path.join(REPO_ROOT, ".pre-commit-config.yaml")
        ),
        ".git/hooks/pre-commit": os.path.exists(
            os.path.join(REPO_ROOT, ".git", "hooks", "pre-commit")
        ),
        "server/ (symlink)": os.path.exists(SERVER_DIR),
    }

    print("  Tools:")
    for name, ok in tools.items():
        icon = "\u2705" if ok else "\u274c"
        label = "installed" if ok else "not found"
        opt = " (optional)" if name == "codeql" and not ok else ""
        print(f"    {icon} {name}: {label}{opt}")

    print("\n  Config files:")
    for name, ok in files.items():
        icon = "\u2705" if ok else "\u274c"
        print(f"    {icon} {name}")

    all_required = tools["ruff"] and tools["pre-commit"]
    print(
        f"\n  {'✅ Ready' if all_required else '❌ Not ready'} for local quality gate"
    )
    return 0


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="sec-02: Local Dev Security Gate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # check
    p_check = sub.add_parser("check", help="Run quality gate checks")
    p_check.add_argument(
        "--quick", action="store_true", help="Quick mode: lint + format only"
    )
    p_check.add_argument(
        "--deep", action="store_true", help="Deep mode: include CodeQL local analysis"
    )
    p_check.add_argument(
        "files",
        nargs="*",
        default=[],
        help="Specific files or directories to scan (default: server/)",
    )

    # setup
    sub.add_parser("setup", help="First-time setup")

    # status
    sub.add_parser("status", help="Show gate readiness")

    args = parser.parse_args()

    if args.command == "check":
        sys.exit(cmd_check(args))
    elif args.command == "setup":
        sys.exit(cmd_setup(args))
    elif args.command == "status":
        sys.exit(cmd_status(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
