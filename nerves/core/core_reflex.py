#!/usr/bin/env python3
"""
angati_reflex.py -- The Cognitive Firewall (Active Pre-Task Gate)
=================================================================
Before any worker executes a task, this module:

  Layer 1: Circuit Breaker  — Has this exact action failed >= 3x? HALT.
  Layer 2: Scar Lookup      — Any semantically similar failures? Inject constraints.
  Layer 3: KG Impact        — What files/functions will this affect? (optional)

Knowledge Space Filtering (type taxonomy):
  angati:    constraint, angati_rule, scar       → ALWAYS enforced
  eais:      eais_lesson, eais_pattern           → enforced for EAIS tasks
  reference: architecture                        → context only, never hard constraint

Committed vs Candidate:
  committed=True  → LLM-verified → injected as hard constraint
  committed=False → Heuristic candidate → shown as advisory only

Usage:
  python angati_reflex.py --task "description of what you are about to do"
  python angati_reflex.py --task "..." --spaces angati eais
"""

import sys

# Configure sys.stdout and sys.stderr to ignore encoding errors (SCAR-019)
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
        sys.stderr.reconfigure(encoding="utf-8", errors="ignore")
    except ValueError as e:
        import logging

        logging.getLogger(__name__).warning("Ignored: %s", e)

import json
from pathlib import Path

AGENTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENTS_ROOT / "tools"))

try:
    import core_scar_memory as scar_memory
except ImportError:
    scar_memory = None

# ── Knowledge Space Definitions ───────────────────────────────────────────
KNOWLEDGE_SPACES = {
    "angati": {
        "types": ["constraint", "angati_rule", "scar"],
        "label": "ANGATI SYSTEM",
        "enforce": True,  # Always injected as hard constraint
        "description": "Core Angati orchestrator rules — always enforced",
    },
    "eais": {
        "types": ["eais_lesson", "eais_pattern"],
        "label": "EAIS LESSON",
        "enforce": True,  # Enforced for EAIS-related tasks
        "description": "EAIS operational lessons from conversation history",
    },
    "reference": {
        "types": ["architecture", "reference"],
        "label": "REFERENCE",
        "enforce": False,  # Context only, never a hard constraint
        "description": "External architectural patterns (Claude Code etc.)",
    },
}

# ── Task Space Detection ───────────────────────────────────────────────────
EAIS_KEYWORDS = [
    "eais",
    "backend",
    "worker",
    "boot",
    "scar",
    "tool",
    "codex",
    "orchestrat",
    "watchdog",
    "auto_learn",
    "reflex",
    "qdrant",
    "celery",
    "fastapi",
    "redis",
    "colab",
    "vllm",
    "traefik",
]
REFERENCE_KEYWORDS = [
    "design",
    "architect",
    "pattern",
    "fork",
    "subagent",
    "claude code",
    "research",
    "principle",
    "framework",
]


def _detect_spaces(instruction: str) -> list[str]:
    """Determine which knowledge spaces to query based on instruction content."""
    instr_lower = instruction.lower()
    spaces = ["angati"]  # Always check angati constraints

    if any(k in instr_lower for k in EAIS_KEYWORDS):
        spaces.append("eais")

    if any(k in instr_lower for k in REFERENCE_KEYWORDS):
        spaces.append("reference")  # Advisory only

    return spaces


def _query_space(instruction: str, space_name: str) -> list[dict]:
    """Query Qdrant filtered by knowledge space types."""
    if not scar_memory:
        return []
    space = KNOWLEDGE_SPACES[space_name]
    try:
        results = scar_memory.consult(instruction, top_k=3)
        # Filter to types relevant to this space
        filtered = [
            r
            for r in results
            if r.get("type", "scar") in space["types"]
            or (
                space_name == "angati" and not r.get("type")
            )  # Legacy untyped scars → angati
        ]
        return filtered
    except Exception:
        return []


def _check_circuit_breaker(instruction: str) -> bool:
    """Layer 1: Has this exact action tripped the circuit breaker?"""
    if not scar_memory:
        return False
    try:
        return scar_memory.circuit_breaker_check(instruction)
    except Exception:
        return False


def run_reflex(instruction: str, requested_spaces: list[str] | None = None) -> str:
    """
    Active cognitive firewall.
    Returns injected constraint string (empty = no constraints found).
    """
    if not scar_memory:
        return ""

    output_sections = []

    # ── Layer 1: Circuit Breaker ─────────────────────────────────────────
    if _check_circuit_breaker(instruction):
        return (
            "\n\n\u26d4 [CRITICAL — ANGATI REFLEX] CIRCUIT BREAKER OPEN: "
            "This exact action has failed \u22653x recently. "
            "DO NOT execute without human investigation."
        )

    # ── Layer 2: Multi-Space Scar Lookup ─────────────────────────────────
    active_spaces = requested_spaces or _detect_spaces(instruction)

    hard_constraints = []  # enforce=True, committed=True
    advisories = []  # enforce=False OR committed=False

    for space_name in active_spaces:
        space = KNOWLEDGE_SPACES[space_name]
        hits = _query_space(instruction, space_name)

        for hit in hits:
            rule = hit.get("prevention_rule", "")
            name = hit.get("name", "")
            committed = hit.get("committed", True)  # Legacy scars default to committed
            label = space["label"]

            if not rule:
                continue

            entry = f"[{label}] {rule}"
            if name:
                entry = f"[{label}] {name}: {rule}"

            if space["enforce"] and committed:
                hard_constraints.append(entry)
            else:
                advisories.append(entry)

    # ── Format output ────────────────────────────────────────────────────
    if hard_constraints:
        section = "\n\n\u26a0\ufe0f ANGATI REFLEX — COGNITIVE FIREWALL \u26a0\ufe0f\n"
        section += "The following constraints are MANDATORY (verified, committed):\n"
        for c in hard_constraints:
            section += f"  \u2022 {c}\n"
        output_sections.append(section)

    if advisories:
        section = "\n\U0001f4cc ANGATI REFLEX — ADVISORY (unverified candidates):\n"
        for a in advisories:
            section += f"  \u2014 {a}\n"
        output_sections.append(section)

    return "".join(output_sections)


# ── CLI ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Angati Reflex — Cognitive Firewall")
    parser.add_argument("--task", required=True, help="Task instruction to check")
    parser.add_argument(
        "--spaces",
        nargs="*",
        choices=["angati", "eais", "reference"],
        help="Override space detection (default: auto)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Output raw JSON hits instead"
    )
    args = parser.parse_args()

    if args.json:
        spaces = args.spaces or _detect_spaces(args.task)
        result = {}
        for s in spaces:
            result[s] = _query_space(args.task, s)
        try:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        except UnicodeEncodeError:
            print(json.dumps(result, indent=2, ensure_ascii=True))
    else:
        output = run_reflex(args.task, args.spaces)
        if output:
            print(output)
        else:
            print("[Reflex] No constraints found. Safe to proceed.")
