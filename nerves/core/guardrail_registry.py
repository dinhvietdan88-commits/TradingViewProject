#!/usr/bin/env python3
"""
Guardrail Registry — Declarative Safety Policies (V2)

Formalizes the Angati hook service's guardrail logic into a
declarative registry, aligning with Google ADK's callback/guardrail
architecture pattern.

Each guardrail is a named policy with:
    - type: Lifecycle hook point (before_tool, after_tool, on_error)
    - tools: Which tools trigger this guardrail ("*" = all)
    - handler: Function name that implements the check
    - short_circuit: If True, a violation blocks execution (ADK: return error)
    - description: Human-readable explanation

Architecture Note:
    This replaces the hardcoded if/elif chains in hook_service.py's
    handle_pre_tool() and handle_post_tool() with a data-driven loop.

Isomorphism:
    ADK before_tool_callback  ↔  Guardrail type="before_tool"
    ADK after_tool_callback   ↔  Guardrail type="after_tool"
    ConsensusEngine GO/BLOCK  ↔  short_circuit=True/False

Changes V1 → V2:
    - Added _resolve_angati_exe() centralized utility
    - Fixed search_scars() bug → consult()
    - Added scar_record_on_error guardrail
    - Added gitnexus_post_commit with shell=False (npx.cmd)
    - B+C+A scar consult integrated via hook_service._scar_consult_fast()

References:
    - KI: google-adk-deep-research §8 (Callback & Guardrail System)
    - antigravity_perspective.md §15 (Native Muscle Exclusivity)
"""

import json
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Shared Utilities
# ---------------------------------------------------------------------------

_angati_exe_cache: Optional[Path] = None


def _resolve_angati_exe() -> Optional[Path]:
    """
    Single source of truth for angati.exe path resolution.
    Caches result after first successful lookup.
    """
    global _angati_exe_cache
    if _angati_exe_cache is not None and _angati_exe_cache.exists():
        return _angati_exe_cache

    candidates = [
        AGENTS_ROOT / "angati.exe",
        AGENTS_ROOT / "tools" / "angati" / "angati.exe",
        AGENTS_ROOT / "spine" / "angati" / "angati.exe",
    ]
    for c in candidates:
        if c.exists():
            _angati_exe_cache = c
            return c
    return None


def _resolve_npx_cmd() -> str:
    """Resolve npx to npx.cmd on Windows for subprocess without shell=False."""
    npx_cmd = Path(r"C:\Program Files\nodejs\npx.cmd")
    if npx_cmd.exists():
        return str(npx_cmd)
    return "npx.cmd"  # Fallback to PATH lookup


# ---------------------------------------------------------------------------
# Guardrail Handler Functions
# ---------------------------------------------------------------------------


def powershell_syntax_check(tool_name: str, tool_input: dict, context: dict) -> dict:
    """
    Windows PowerShell Syntax Guard — prevents running invalid bash statements/operators,
    unrecognized unix commands, and improper command argument quoting on Windows.
    """
    if sys.platform != "win32":
        return {"verdict": "ALLOW"}

    cmd_line = tool_input.get("CommandLine", "")
    if not cmd_line:
        return {"verdict": "ALLOW"}

    errors = []
    if "&&" in cmd_line:
        errors.append(
            "Invalid operator '&&' in PowerShell. Use ';' or run commands sequentially, or use a Python script."
        )
    if "||" in cmd_line:
        errors.append(
            "Invalid operator '||' in PowerShell. Use try/catch or if/else, or run a Python script."
        )
    if "cat <<" in cmd_line or "<< EOF" in cmd_line:
        errors.append(
            "Invalid heredoc '<<' in Windows PowerShell. Use write_to_file or a Python script."
        )

    # Validate gh api stopping-parser usage
    if "gh api" in cmd_line and "--%" not in cmd_line:
        errors.append(
            "Potential 'gh api' argument parsing error. Always use the PowerShell stop-parsing operator '--%' (e.g. 'gh api --% repos/...') or quote your arguments to prevent PowerShell from splitting them."
        )

    # Validate jq quoting/interpolation issues in PowerShell
    if "jq" in cmd_line and '"' in cmd_line:
        if "\\(" in cmd_line or "(" in cmd_line:
            if any(
                p in cmd_line for p in (".name", ".conclusion", ".status", ".state")
            ):
                errors.append(
                    "PowerShell subexpression evaluation detected in 'jq' filter. Wrap 'jq' queries in single quotes (') instead of double quotes (\") to prevent PowerShell from executing '\\(.name)' as a command."
                )

    # Validate Unix commands (including piped or chained commands like | grep)
    import re

    unix_match = re.search(r"(?:^|\||;)\s*(grep|sed|awk)\b", cmd_line.lower())
    if unix_match:
        binary = unix_match.group(1)
        errors.append(
            f"Unix binary '{binary}' is not natively supported on Windows. Use python scripts, python -c, or native tools (e.g. grep_search)."
        )

    if errors:
        return {
            "verdict": "BLOCK",
            "reason": " | ".join(errors),
            "remediation": "Rewrite the command using valid PowerShell syntax (e.g., replace '&&' with ';'), use Python, or use native file/search tools.",
        }

    return {"verdict": "ALLOW"}


def kg_guard_check(tool_name: str, tool_input: dict, context: dict) -> dict:
    """
    Knowledge Graph Guard — prevents writes to protected files.

    Maps to ADK: before_tool_callback with short-circuit.
    Maps to Angati: ConsensusEngine BLOCK verdict.
    """
    target_file = tool_input.get("TargetFile", "")
    if not target_file:
        return {"verdict": "ALLOW"}

    angati_exe = _resolve_angati_exe()
    if not angati_exe:
        return {
            "verdict": "ALLOW",
            "reason": "angati.exe not found — allowing by default",
        }

    try:
        res = subprocess.run(
            [
                str(angati_exe),
                "kg",
                "guard",
                "--file",
                str(target_file),
                "--action",
                "edit",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=15,
            check=False,
        )
        if res.returncode == 2:
            return {
                "verdict": "BLOCK",
                "reason": f"KG Guard blocked write to {target_file} (Exit Code 2)",
                "remediation": r"Write sandbox patch to C:\Users\pesil\EAIS\_sandbox_patches\ instead.",
            }
        elif res.returncode == 1:
            return {"verdict": "WARN", "reason": f"KG Guard caution for {target_file}"}
    except subprocess.TimeoutExpired:
        return {
            "verdict": "ALLOW",
            "reason": "KG Guard timed out — allowing by default",
        }
    except Exception as exc:
        return {"verdict": "ALLOW", "reason": f"KG Guard error: {exc}"}

    return {"verdict": "ALLOW"}


def circuit_breaker_check(tool_name: str, tool_input: dict, context: dict) -> dict:
    """
    Circuit Breaker — prevents repeated failure patterns.

    Maps to ADK: before_tool_callback with short-circuit.
    Maps to Angati: Amygdala scar-driven pattern detection.
    """
    scar_memory = context.get("scar_memory")
    if not scar_memory:
        return {"verdict": "ALLOW", "reason": "scar_memory not available"}

    instruction = f"Executing tool {tool_name} with arguments: {json.dumps(tool_input)}"

    try:
        if scar_memory.circuit_breaker_check(instruction):
            return {
                "verdict": "BLOCK",
                "reason": "Circuit breaker tripped: This exact failure pattern has occurred >= 3 times in 1 hour.",
            }
    except Exception as exc:
        return {"verdict": "ALLOW", "reason": f"Circuit breaker error: {exc}"}

    return {"verdict": "ALLOW"}


def scar_consult_advisory(tool_name: str, tool_input: dict, context: dict) -> dict:
    """
    Scar Consultation — advisory check against historical failures.

    Uses the B+C+A fast consult from hook_service if available,
    falls back to scar_memory.consult() subprocess.

    Maps to ADK: before_tool_callback without short-circuit (advisory only).
    Maps to Angati: Hippocampus long-term memory consultation.
    """
    cmd_line = tool_input.get("CommandLine", "")
    if not cmd_line:
        return {"verdict": "ALLOW"}

    # Try the optimized B+C+A fast path (injected by hook_service)
    fast_consult = context.get("scar_consult_fast")
    if fast_consult:
        advisory = fast_consult(cmd_line)
        if advisory:
            return {
                "verdict": "WARN",
                "reason": f"Similar command failed before: {advisory}",
            }
        return {"verdict": "ALLOW"}

    # Fallback: direct scar_memory.consult()
    scar_memory = context.get("scar_memory")
    if not scar_memory:
        return {"verdict": "ALLOW"}

    try:
        results = scar_memory.consult(cmd_line, top_k=3)
        if results:
            relevant = [s for s in results if s.get("score", 0) >= 0.82]
            if relevant:
                rules = [
                    s.get("prevention_rule", "")
                    for s in relevant
                    if s.get("prevention_rule")
                ]
                if rules:
                    return {
                        "verdict": "WARN",
                        "reason": f"Similar command failed before: {' | '.join(rules[:2])}",
                    }
    except ValueError as e:
        import logging

        logging.getLogger(__name__).warning("Ignored: %s", e)

    return {"verdict": "ALLOW"}


def reflex_advisory(tool_name: str, tool_input: dict, context: dict) -> dict:
    """
    Reflex System — keyword-triggered skill advisory.

    Maps to ADK: contextual awareness callbacks.
    Maps to Angati: ReflexSvc (keyword → SKILL.md).
    """
    reflex = context.get("reflex")
    if not reflex:
        return {"verdict": "ALLOW"}

    instruction = f"Executing tool {tool_name} with arguments: {json.dumps(tool_input)}"
    try:
        output = reflex.run_reflex(instruction)
        if output:
            return {"verdict": "ALLOW", "advisory": output}
    except ValueError as e:
        import logging

        logging.getLogger(__name__).warning("Ignored: %s", e)

    return {"verdict": "ALLOW"}


def gitnexus_post_commit(tool_name: str, tool_input: dict, context: dict) -> dict:
    """
    GitNexus Post-Commit — updates knowledge graph after git operations.

    Maps to ADK: after_tool_callback.
    Maps to Angati: Post-commit KG ingestion.
    """
    cmd_line = tool_input.get("CommandLine", "").lower()
    if "git commit" not in cmd_line and "git merge" not in cmd_line:
        return {"verdict": "SKIP"}

    try:
        npx_cmd = _resolve_npx_cmd()
        subprocess.run(
            [npx_cmd, "gitnexus", "analyze", "--embeddings"],
            cwd=str(AGENTS_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=120,
            check=False,
        )
    except Exception as exc:
        return {"verdict": "ALLOW", "reason": f"gitnexus error: {exc}"}

    return {"verdict": "ALLOW", "action": "gitnexus_analyze_completed"}


def memory_stats_post_commit(tool_name: str, tool_input: dict, context: dict) -> dict:
    """
    Memory Stats — refresh stats after git operations.
    """
    cmd_line = tool_input.get("CommandLine", "").lower()
    if "git commit" not in cmd_line and "git merge" not in cmd_line:
        return {"verdict": "SKIP"}

    angati_exe = _resolve_angati_exe()
    if not angati_exe:
        return {"verdict": "ALLOW"}

    try:
        subprocess.run(
            [str(angati_exe), "memory", "stats"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=15,
            check=False,
        )
    except Exception as exc:
        return {"verdict": "ALLOW", "reason": f"memory stats error: {exc}"}

    return {"verdict": "ALLOW"}


# Error patterns for run_command failure detection in post-tool
_ERROR_PATTERNS = [
    "SyntaxError",
    "NameError",
    "TypeError",
    "ImportError",
    "ModuleNotFoundError",
    "FileNotFoundError",
    "PermissionError",
    "TimeoutExpired",
    "ConnectionRefusedError",
    "OSError",
    "ValueError",
    "KeyError",
    "IndexError",
    "AttributeError",
    "Traceback (most recent call last)",
    "command not found",
    "is not recognized",
    "The term",
    "CommandNotFoundException",
    "Access is denied",
    "ENOENT",
]


def error_detect_post_tool(tool_name: str, tool_input: dict, context: dict) -> dict:
    """
    Error Detection — catches run_command failures in post-tool output.

    Bridges the gap where IDE does NOT call /on-error for run_command
    failures. Inspects tool_output for error patterns and records scars.

    This guardrail fires on after_tool for run_command, inspects the
    output text, and if error patterns are found + exit code != 0,
    delegates to scar_record_on_error.
    """
    # Only run_command has meaningful output to inspect
    tool_output = context.get("tool_output", "")
    if not tool_output:
        return {"verdict": "SKIP"}

    # Normalize output to string
    output_str = ""
    exit_code = None
    if isinstance(tool_output, dict):
        output_str = str(tool_output.get("Output", "")) + str(
            tool_output.get("Stderr", "")
        )
        exit_code = tool_output.get("ExitCode")
    else:
        output_str = str(tool_output)

    # Check for exit code failure
    if exit_code is not None and exit_code == 0:
        return {"verdict": "SKIP", "reason": "exit code 0 — no error"}

    # Scan for error patterns
    detected = []
    for pattern in _ERROR_PATTERNS:
        if pattern in output_str:
            detected.append(pattern)

    if not detected:
        return {"verdict": "SKIP", "reason": "no error patterns detected"}

    # Error detected! Delegate to scar recording
    error_snippet = output_str[:500]
    context["error"] = error_snippet
    result = scar_record_on_error(tool_name, tool_input, context)

    # Enhance the result
    patterns_found = ", ".join(detected[:3])
    result["action"] = f"error_detected_post_tool:{patterns_found}"
    print(
        f"[SRA Server] Error detected in post-tool output: {patterns_found}",
        file=sys.stderr,
    )

    return result


_scar_record_queue = queue.Queue()


def _scar_record_worker():
    while True:
        task = _scar_record_queue.get()
        if task is None:
            break
        (
            failed_action,
            error_msg,
            tool_name,
            cache_invalidator,
            context_name,
            prevention_rule,
        ) = task
        try:
            import core_scar_memory as scar_memory

            if scar_memory:
                scar_memory.record_scar(
                    failed_action=failed_action,
                    error_signature=error_msg[:300],
                    recovery_action="",
                    prevention_rule=prevention_rule,
                    context=context_name,
                )
                if cache_invalidator:
                    cache_invalidator(failed_action)
        except Exception as e:
            print(f"[SRA Async Worker] Error recording scar: {e}", file=sys.stderr)
        finally:
            _scar_record_queue.task_done()


_worker_thread = threading.Thread(target=_scar_record_worker, daemon=True)
_worker_thread.start()


def scar_record_on_error(tool_name: str, tool_input: dict, context: dict) -> dict:
    """
    Scar Recording — records failures to scar memory for future consultation asynchronously.

    Closes the feedback loop: /on-error → scar record → /pre-tool scar consult.
    Records scars for run_command AND file write failures.

    Maps to ADK: on_error callback.
    """
    error_msg = context.get("error", "") or context.get("tool_output", "")
    if isinstance(error_msg, dict):
        error_msg = json.dumps(error_msg)[:500]
    else:
        error_msg = str(error_msg)[:500]

    # Determine what failed
    if tool_name == "run_command":
        cmd_line = tool_input.get("CommandLine", "unknown command")
        failed_action = cmd_line[:300]
        prevention_rule = f"Command failed: {cmd_line[:100]}. Error: {error_msg[:150]}"
    elif tool_name in {
        "write_to_file",
        "replace_file_content",
        "multi_replace_file_content",
    }:
        target_file = tool_input.get("TargetFile", "unknown file")
        failed_action = f"Write to {target_file}"
        prevention_rule = f"File write failed: {target_file}. Error: {error_msg[:150]}"
    else:
        failed_action = f"Tool {tool_name}"
        prevention_rule = f"Tool {tool_name} failed. Error: {error_msg[:200]}"

    cache_invalidator = context.get("cache_invalidator")
    context_name = f"hook_on_error/{tool_name}"

    _scar_record_queue.put(
        (
            failed_action,
            error_msg,
            tool_name,
            cache_invalidator,
            context_name,
            prevention_rule,
        )
    )

    return {"verdict": "ALLOW", "action": f"scar_recorded_queued:{tool_name}"}


# ---------------------------------------------------------------------------
# Guardrail Registry (The Data-Driven Backbone)
# ---------------------------------------------------------------------------

FILE_WRITING_TOOLS = frozenset(
    {
        "write_to_file",
        "replace_file_content",
        "multi_replace_file_content",
    }
)

GUARDRAILS = {
    # ── before_tool (pre-tool) ──
    "powershell_syntax": {
        "type": "before_tool",
        "tools": {"run_command"},
        "handler": powershell_syntax_check,
        "short_circuit": True,
        "description": "Windows PowerShell Syntax Guard — prevents running invalid statement separators/operators on Windows",
    },
    "kg_guard": {
        "type": "before_tool",
        "tools": FILE_WRITING_TOOLS,
        "handler": kg_guard_check,
        "short_circuit": True,
        "description": "Knowledge Graph Guard — blocks writes to protected files",
    },
    "circuit_breaker": {
        "type": "before_tool",
        "tools": {"*"},  # Applies to all tools
        "handler": circuit_breaker_check,
        "short_circuit": True,
        "description": "Circuit Breaker — prevents repeated failure patterns",
    },
    "scar_consult": {
        "type": "before_tool",
        "tools": {"run_command"},
        "handler": scar_consult_advisory,
        "short_circuit": False,
        "description": "Scar Consultation — advisory check against historical failures",
    },
    "reflex": {
        "type": "before_tool",
        "tools": {"*"},
        "handler": reflex_advisory,
        "short_circuit": False,
        "description": "Reflex System — keyword-triggered skill advisory",
    },
    # ── after_tool (post-tool) ──
    "gitnexus_post_commit": {
        "type": "after_tool",
        "tools": {"run_command"},
        "handler": gitnexus_post_commit,
        "short_circuit": False,
        "description": "GitNexus Post-Commit — KG update after git operations",
    },
    "memory_stats_post_commit": {
        "type": "after_tool",
        "tools": {"run_command"},
        "handler": memory_stats_post_commit,
        "short_circuit": False,
        "description": "Memory Stats — refresh after git operations",
    },
    "error_detect": {
        "type": "after_tool",
        "tools": {"run_command"},
        "handler": error_detect_post_tool,
        "short_circuit": False,
        "description": "Error Detection — catches run_command errors in post-tool (bridges IDE gap)",
    },
    # ── on_error ──
    "scar_record": {
        "type": "on_error",
        "tools": {"*"},  # Record scars for ALL tool errors
        "handler": scar_record_on_error,
        "short_circuit": False,
        "description": "Scar Recording — records failures for future prevention",
    },
}


# ---------------------------------------------------------------------------
# Guardrail Evaluation Engine
# ---------------------------------------------------------------------------


def evaluate_guardrails(
    lifecycle_type: str, tool_name: str, tool_input: dict, context: dict = None
) -> dict:
    """
    Evaluate all guardrails matching the given lifecycle type and tool.

    Args:
        lifecycle_type: "before_tool", "after_tool", or "on_error"
        tool_name: Name of the tool being invoked
        tool_input: Tool arguments
        context: Additional context (scar_memory, reflex, etc.)

    Returns:
        dict with keys:
            - decision: "allow" | "deny"
            - verdicts: List of individual guardrail results
            - message: Denial reason if blocked
            - advisory: Combined advisory text if any
    """
    if context is None:
        context = {}

    verdicts = []
    blocked = False
    block_message = ""
    advisories = []

    for name, guardrail in GUARDRAILS.items():
        if guardrail["type"] != lifecycle_type:
            continue

        # Check if this guardrail applies to the current tool
        tools = guardrail["tools"]
        if "*" not in tools and tool_name not in tools:
            continue

        # Execute the guardrail handler
        try:
            result = guardrail["handler"](tool_name, tool_input, context)
            result["guardrail"] = name
            verdicts.append(result)

            # Collect advisories
            if result.get("advisory"):
                advisories.append(result["advisory"])
            if result.get("verdict") == "WARN" and result.get("reason"):
                advisories.append(result["reason"])

            # Short-circuit on BLOCK
            if guardrail["short_circuit"] and result.get("verdict") == "BLOCK":
                blocked = True
                block_message = result.get("reason", f"Blocked by guardrail: {name}")
                break

        except Exception as exc:
            verdicts.append({"guardrail": name, "verdict": "ERROR", "reason": str(exc)})

    return {
        "decision": "deny" if blocked else "allow",
        "message": block_message
        if blocked
        else (" | ".join(advisories) if advisories else ""),
        "verdicts": verdicts,
    }
