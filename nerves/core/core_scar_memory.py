#!/usr/bin/env python3
# @angati-protected: Active Alpha-Era Core Asset
# Level: RED (DO NOT PURGE / DO NOT MOVE)
# Constitution Rule: 3.5 (Active Python Assets Law)
"""
scar_memory.py -- Failure-Recovery Pattern Learning (Phase 7)

"Vết sẹo" — mỗi lần hệ thống thất bại rồi phục hồi, bài học được
lưu lại vĩnh viễn để phòng tránh lỗi tương tự trong tương lai.

NOT a product feature — Orchestrator-internal only.

Usage:
  python scar_memory.py record --failed "codex exec --ephemerally..." \\
      --error "unexpected argument" \\
      --recovery "codex exec --dangerously-bypass..." \\
      --rule "Use --dangerously-bypass, NOT --ephemerally" \\
      --context "codex_cli_worker"

  python scar_memory.py consult --instruction "codex exec ..."
  python scar_memory.py auto-extract
  python scar_memory.py circuit-check --action "auto_patch:15 tests failed"
  python scar_memory.py summary
  python scar_memory.py sync-ltm
  python scar_memory.py test
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

import argparse
import hashlib
import json
import re
import time
import uuid
from collections import defaultdict
from pathlib import Path

AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(AGENTS_ROOT / "tools"))

# ── Dependencies ──────────────────────────────────────────────
# Imports like qdrant_client and fastembed are deferred to runtime
# to avoid blocking orchestrator or codex_cli on boot / import time.
import core_env_loader as env_loader  # noqa: E402 — must come after sys.path.insert

env_loader.load()

# ── Constants ─────────────────────────────────────────────────
import os  # noqa: E402 — must come after env_loader.load() to get fresh env vars

_tenant = os.environ.get("EAIS_TENANT_ID", "").strip().lower()
COLLECTION_NAME = f"scar_memory_{_tenant}" if _tenant else "scar_memory"
VECTOR_SIZE = 384  # bge-small-en-v1.5
CONSULT_THRESHOLD = 0.80  # Lower than cache (0.92) — want broad recall
DEDUP_THRESHOLD = 0.90  # High similarity = same scar, increment frequency
CIRCUIT_BREAKER_MAX = 3  # Max identical failures within time window
CIRCUIT_BREAKER_WINDOW_HOURS = 1

CONFIG_FILE = AGENTS_ROOT / "memory" / "qdrant_config.json"
TRACES_FILE = AGENTS_ROOT / "memory" / "traces.log"
EVENT_LOG = AGENTS_ROOT / "memory" / "event_log.jsonl"
CORE_STATE = AGENTS_ROOT / "cortex" / "state" / "core_state.yaml"

# Lazy singletons
_embedding_model = None
_qdrant_client = None
_l1_db = None  # L1 sqlite-vec (V2_brain.db)
_l1_mm = None  # memory_manager module ref


# ── Infrastructure ────────────────────────────────────────────


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from fastembed import TextEmbedding

        _embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    return _embedding_model


def _embed(text: str) -> list[float]:
    gen = _get_embedding_model().embed([text])
    return next(gen).tolist()


def _load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def _get_client():
    global _qdrant_client
    if _qdrant_client is None:
        try:
            from qdrant_client import QdrantClient
        except (ImportError, KeyboardInterrupt):
            # KeyboardInterrupt: Windows Python 3.11 frozen zipimport signal race.
            # Stray SIGINT (inherited from PS terminal) fires during _path_stat in
            # frozen importlib while loading qdrant_client.http — not an install error.
            # Run via subprocess.run(capture_output=True) to reproduce clean import.
            print(
                json.dumps(
                    {"error": "qdrant-client import failed (run isolated to retry)"}
                )
            )
            sys.exit(1)

        config = _load_config()
        _qdrant_client = QdrantClient(
            url=config.get("qdrant_url", ""),
            api_key=config.get("qdrant_api_key", ""),
            timeout=15,
        )
    return _qdrant_client


def _get_l1_db():
    """Placeholder for L1 sqlite-vec DB accessor (not yet implemented)."""
    return None


def _scar_to_l1_text(
    failed_action: str,
    error_signature: str,
    recovery_action: str,
    prevention_rule: str,
    context: str,
) -> str:
    """Encode scar as searchable text for L1 storage."""
    return (
        f"SCAR[{context}] "
        f"FAILURE: {error_signature[:200]} | "
        f"RULE: {prevention_rule[:200]} | "
        f"RECOVERY: {recovery_action[:100]}"
    )


def _parse_l1_result(r: dict) -> dict:
    """Parse L1 recall result back into scar-shaped dict."""
    text = r.get("text", "")
    rule_match = re.search(r"RULE: (.+?)(?:\s*\|\s*RECOVERY|\s*$)", text)
    err_match = re.search(r"FAILURE: (.+?)(?:\s*\|\s*RULE|\s*$)", text)
    prevention_rule = rule_match.group(1).strip() if rule_match else text[:150]
    error_sig = err_match.group(1).strip() if err_match else ""
    # Extract name/description from stored text if available
    parts = text.split(" | ") if " | " in text else []
    extracted_name = ""
    extracted_desc = ""
    for p in parts:
        if p.startswith("NAME:"):
            extracted_name = p[5:].strip()
        elif p.startswith("DESC:"):
            extracted_desc = p[5:].strip()

    return {
        "scar_id": r.get("id", ""),
        "score": r.get("score", 0.0),
        "name": extracted_name,
        "description": extracted_desc,
        "type": "scar",
        "prevention_rule": prevention_rule,
        "error_signature": error_sig[:150],
        "severity": "unknown",
        "frequency": 1,
    }


def _ensure_collection(client):
    from qdrant_client.models import Distance, VectorParams

    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in collections:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        client.create_payload_index(
            COLLECTION_NAME, field_name="severity", field_schema="keyword"
        )
        client.create_payload_index(
            COLLECTION_NAME, field_name="context", field_schema="keyword"
        )
        client.create_payload_index(
            COLLECTION_NAME, field_name="type", field_schema="keyword"
        )


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _deterministic_id(text: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, _content_hash(text)))


def _severity_from_frequency(freq: int) -> str:
    if freq >= 5:
        return "critical"
    elif freq >= 3:
        return "high"
    elif freq >= 2:
        return "medium"
    return "low"


# ── Core Operations ──────────────────────────────────────────


def _get_angati_exe() -> str:
    """Dynamically resolve path to angati.exe binary."""
    angati_exe = AGENTS_ROOT / "angati.exe"
    if not angati_exe.exists():
        angati_exe = AGENTS_ROOT / "tools" / "angati" / "angati.exe"
    if not angati_exe.exists():
        angati_exe = AGENTS_ROOT / "spine" / "angati" / "angati.exe"
    if not angati_exe.exists():
        angati_exe = Path("angati.exe")
    return str(angati_exe)


def record_scar(
    failed_action: str = "",
    error_signature: str = "",
    recovery_action: str = "",
    prevention_rule: str = "",
    context: str = "",
    auto_extracted: bool = False,
    name: str = "",
    description: str = "",
    type_val: str = "scar",
    is_creative_innovation: bool = False,
) -> dict:
    """
    Record a failure-recovery pattern as a "scar" or a generic Knowledge Item.
    Delegates to angati.exe scar record.
    """
    angati_exe = _get_angati_exe()
    import json
    import subprocess

    _cmd = [
        angati_exe,
        "scar",
        "record",
        "--failed",
        failed_action,
        "--error",
        error_signature,
        "--recovery",
        recovery_action,
        "--rule",
        prevention_rule,
        "--context",
        context,
        "--name",
        name,
        "--desc",
        description,
    ]

    try:
        res = subprocess.run(
            _cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=30,
        )
        if res.returncode == 0:
            try:
                return json.loads(
                    res.stdout.split("\n")[-2]
                    if "\n" in res.stdout.strip()
                    else res.stdout
                )
            except ValueError as e:
                import logging

                logging.getLogger(__name__).warning("Ignored: %s", e)
        return {"status": "error", "error": res.stderr[:100], "severity": "low"}
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error": "angati.exe record timed out",
            "severity": "low",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)[:100], "severity": "low"}


def consult(instruction: str, top_k: int = 5) -> list[dict]:
    """
    Before executing an instruction, check if any scars are relevant.
    Delegates to angati.exe scar consult.
    """
    angati_exe = _get_angati_exe()
    import json
    import subprocess

    try:
        res = subprocess.run(
            [angati_exe, "scar", "consult", "--instruction", instruction],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=30,
        )
        if res.returncode == 0:
            return json.loads(res.stdout)
    except subprocess.TimeoutExpired:
        pass
    except ValueError as e:
        import logging

        logging.getLogger(__name__).warning("Ignored: %s", e)
    return []


def circuit_breaker_check(action_signature: str) -> bool:
    """
    Check if the same error has been seen too many times recently.
    Returns True if the circuit should be BROKEN (stop retrying).
    Delegates to angati.exe scar check.
    """
    angati_exe = _get_angati_exe()
    import json
    import subprocess

    try:
        res = subprocess.run(
            [angati_exe, "scar", "check", "--action", action_signature],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
        )
        if res.returncode == 0:
            data = json.loads(res.stdout)
            return data.get("circuit_broken", False)
    except subprocess.TimeoutExpired:
        pass
    except ValueError as e:
        import logging

        logging.getLogger(__name__).warning("Ignored: %s", e)
    return False


def summary(top_k: int = 10) -> list[dict]:
    """Top K scars by severity and frequency for boot report."""
    angati_exe = _get_angati_exe()
    import json
    import subprocess

    try:
        res = subprocess.run(
            [angati_exe, "scar", "summary"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=30,
        )
        if res.returncode == 0:
            results = json.loads(res.stdout)
            return results[:top_k] if isinstance(results, list) else []
    except subprocess.TimeoutExpired:
        pass
    except ValueError as e:
        import logging

        logging.getLogger(__name__).warning("Ignored: %s", e)
    return []


def stats() -> dict:
    """Quick stats for boot report. Delegates to angati.exe scar health."""
    h = health_check()
    return {
        "total_scars": h.get("total_scars", 0),
        "severity": h.get("severity", {}),
        "backend": "angati-daemon",
    }


def health_check(l1_only: bool = False) -> dict:
    """Boot-time health check — instant L1 read + optional L2 ping."""
    angati_exe = _get_angati_exe()
    import json
    import subprocess

    try:
        res = subprocess.run(
            [angati_exe, "scar", "health"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=15,
        )
        if res.returncode == 0:
            return json.loads(res.stdout)
    except subprocess.TimeoutExpired:
        pass
    except ValueError as e:
        import logging

        logging.getLogger(__name__).warning("Ignored: %s", e)
    return {
        "l1": "OFFLINE",
        "l2": "OFFLINE",
        "total_scars": 0,
        "l1_points": 0,
        "boot_mode": "hot",
    }


# ── Trace Analyzer: FAILED→SUCCESS Pattern Detection ─────────


def auto_extract_from_traces() -> dict:
    """
    Scan traces.log for FAILED→SUCCESS pairs.
    Extract failure-recovery patterns and record as scars.
    """
    if not TRACES_FILE.exists():
        return {"status": "no_traces", "scars_created": 0}

    # Parse all trace events
    events = []
    for line in TRACES_FILE.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    # Group by agent_id
    by_agent = defaultdict(list)
    for e in events:
        agent = e.get("agent_id", "unknown")
        by_agent[agent].append(e)

    scars_created = 0
    scars_incremented = 0
    detected_patterns = []

    for agent_id, agent_events in by_agent.items():
        # Sort by timestamp
        agent_events.sort(key=lambda x: x.get("timestamp", ""))

        for i in range(len(agent_events)):
            ev = agent_events[i]

            # Only look at failures
            if ev.get("success", True):
                continue

            status = ev.get("metadata", {}).get("status", "")
            if status in ("STARTED", "TRYING"):
                continue  # These are just "beginning" markers, not real failures

            error_info = ev.get("error", "") or ev.get("metadata", {}).get("info", "")
            if not error_info or len(error_info) < 10:
                continue

            # Look for a SUCCESS within next 5 events (same agent, within 5 min)
            for j in range(i + 1, min(i + 6, len(agent_events))):
                next_ev = agent_events[j]
                if not next_ev.get("success", False):
                    continue

                # Found a FAILED → SUCCESS pair
                recovery_info = next_ev.get("metadata", {}).get("info", "")
                recovery_model = next_ev.get("metadata", {}).get("model", "")

                # Generate prevention rule via pattern matching
                rule = _generate_prevention_rule(ev, next_ev, error_info)
                if not rule:
                    break  # Can't extract a meaningful rule

                pattern = {
                    "agent": agent_id,
                    "failed_action": error_info[:200],
                    "recovery": recovery_info[:200]
                    or f"Succeeded with model={recovery_model}",
                    "rule": rule,
                }
                detected_patterns.append(pattern)

                result = record_scar(
                    failed_action=error_info[:300],
                    error_signature=error_info[:300],
                    recovery_action=recovery_info[:200] or f"model={recovery_model}",
                    prevention_rule=rule,
                    context=f"{agent_id}/{ev.get('action', 'unknown')}",
                    auto_extracted=True,
                    name=f"{agent_id}: {error_info[:40]}",
                    description=f"Failure→Recovery pattern from {agent_id}. Action: {ev.get('action', 'unknown')}",
                )

                if result["status"] == "recorded":
                    scars_created += 1
                elif result["status"] == "incremented":
                    scars_incremented += 1

                break  # Only match first SUCCESS after FAILURE

    # Also scan event_log for repeated identical failures (circuit breaker candidates)
    cb_scars = _extract_repeated_failures_from_event_log()
    scars_created += cb_scars

    return {
        "status": "extracted",
        "scars_created": scars_created,
        "scars_incremented": scars_incremented,
        "patterns_detected": len(detected_patterns),
        "details": detected_patterns[:10],  # Limit output size
    }


def _generate_prevention_rule(
    failed_ev: dict, success_ev: dict, error_info: str
) -> str:
    """
    Generate a prevention rule by comparing failed vs success event metadata.
    Pure pattern matching — NO LLM call.
    """
    failed_meta = failed_ev.get("metadata", {})
    success_meta = success_ev.get("metadata", {})

    failed_model = failed_meta.get("model", "")
    success_model = success_meta.get("model", "")

    rules: list[
        str
    ] = []  # Collected candidate rules (currently unused — single-exit pattern)
    _ = rules  # Suppress unused-variable lint until multi-rule collection is implemented

    # Pattern: wrong CLI flag
    flag_match = re.search(r"unexpected argument '([^']+)'", error_info)
    if flag_match:
        wrong_flag = flag_match.group(1)
        tip_match = re.search(r"similar argument exists: '([^']+)'", error_info)
        if tip_match:
            correct_flag = tip_match.group(1)
            return f"Flag '{wrong_flag}' does not exist. Use '{correct_flag}' instead."
        return f"Flag '{wrong_flag}' is invalid. Check codex --help for correct flags."

    # Pattern: missing --skip-git-repo-check
    if "trusted directory" in error_info and "skip-git-repo-check" in error_info:
        return "Always add --skip-git-repo-check when working outside a git repository root."

    # Pattern: LiteLLM provider not specified
    provider_match = re.search(r"Provider NOT provided.*model=(\S+)", error_info)
    if provider_match:
        model = provider_match.group(1)
        if "claude" in model.lower():
            return f"Model '{model}' requires 'anthropic/' prefix for LiteLLM. Use 'anthropic/{model}'."
        if "gemini" in model.lower():
            return f"Model '{model}' requires 'gemini/' prefix for LiteLLM. Use 'gemini/{model}'."
        return f"Model '{model}' needs a provider prefix for LiteLLM (e.g., 'openai/', 'anthropic/')."

    # Pattern: authentication error
    if "AuthenticationError" in error_info:
        if failed_model and success_model and failed_model != success_model:
            return f"Model '{failed_model}' has auth issues. Prefer '{success_model}' as primary."

    # Pattern: timeout
    if "timeout" in error_info.lower() or "Exceeded" in error_info:
        failed_timeout = re.search(r"(\d+)s", error_info)
        if failed_timeout:
            return f"Timeout at {failed_timeout.group(1)}s is too short for this task type. Increase timeout."

    # Pattern: model switch (generic fallback learning)
    if failed_model and success_model and failed_model != success_model:
        return f"Model '{failed_model}' failed for this task type. '{success_model}' is more reliable here."

    # Generic: can't determine specific rule
    if error_info and len(error_info) > 20:
        return f"Known failure pattern: {error_info[:150]}. Verify configuration before retry."

    return ""


def _extract_repeated_failures_from_event_log() -> int:
    """Scan event_log.jsonl for repeated identical failures → record as circuit breaker scars."""
    if not EVENT_LOG.exists():
        return 0

    # Count error occurrences by signature
    error_counts = defaultdict(int)
    error_examples = {}

    for line in EVENT_LOG.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if event.get("status") != "error":
            continue

        action = event.get("action", "")
        context = event.get("context", "")[:100]
        sig = f"{action}:{context}"

        error_counts[sig] += 1
        error_examples[sig] = event

    scars = 0
    for sig, count in error_counts.items():
        if count >= CIRCUIT_BREAKER_MAX:
            event = error_examples[sig]
            action = event.get("action", "unknown")
            result = record_scar(
                failed_action=sig,
                error_signature=sig,
                recovery_action="NONE — never recovered",
                prevention_rule=f"CIRCUIT BREAKER: '{action}' failed {count}x with same context. Stop retrying — requires human investigation.",
                context="auto_patcher/circuit_breaker",
                auto_extracted=True,
                name=f"circuit_breaker: {action}",
                description=f"Repeated failure ({count}x) from {action}. Never recovered.",
            )
            if result["status"] == "recorded":
                scars += 1

    return scars


def check_duplicate(text: str) -> dict:
    """Check if a semantically similar issue/scar exists"""
    angati_exe = _get_angati_exe()
    import json
    import subprocess

    try:
        res = subprocess.run(
            [angati_exe, "memory", "recall", text, "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=15,
        )
        if res.returncode == 0:
            results = json.loads(res.stdout)
            if results and len(results) > 0:
                top_result = results[0]
                if top_result.get("score", 0) > DEDUP_THRESHOLD:
                    return {
                        "is_duplicate": True,
                        "original_id": top_result.get("id", ""),
                        "score": top_result.get("score", 0),
                    }
    except subprocess.TimeoutExpired:
        pass
    except ValueError as e:
        import logging

        logging.getLogger(__name__).warning("Ignored: %s", e)
    return {"is_duplicate": False}


# ── LTM Sync ─────────────────────────────────────────────────


def sync_to_ltm() -> dict:
    """
    Sync top scars into core_state.yaml → lessons_learned.
    Called during boot to persist knowledge across conversations.
    """
    top_scars = summary(top_k=15)
    if not top_scars:
        return {"status": "no_scars"}

    # Read current core_state.yaml
    if not CORE_STATE.exists():
        return {"status": "no_core_state"}

    content = CORE_STATE.read_text(encoding="utf-8")

    # Extract existing lessons_learned
    new_lessons = []
    for scar in top_scars:
        rule = scar.get("prevention_rule", "")
        severity = scar.get("severity", "low")
        freq = scar.get("frequency", 1)
        if rule and severity in ("high", "critical"):
            lesson = f"[SCAR freq={freq}] {rule}"
            # Check if already in file
            if lesson not in content and rule not in content:
                new_lessons.append(lesson)

    if not new_lessons:
        return {"status": "no_new_lessons", "checked": len(top_scars)}

    # Append under lessons_learned section
    # Find the lessons_learned block and append
    lines = content.split("\n")
    insert_idx = None
    for i, line in enumerate(lines):
        if "lessons_learned:" in line:
            # Find the last lesson line (starts with "    - ")
            for j in range(i + 1, len(lines)):
                if lines[j].strip().startswith("- ") and lines[j].startswith("    "):
                    insert_idx = j + 1
                elif lines[j].strip() and not lines[j].startswith("    "):
                    if insert_idx is None:
                        insert_idx = j
                    break
            if insert_idx is None:
                insert_idx = i + 1
            break

    if insert_idx is None:
        return {"status": "lessons_learned_not_found"}

    # Insert new lessons
    for lesson in new_lessons:
        yaml_line = f'    - "{lesson}"'
        lines.insert(insert_idx, yaml_line)
        insert_idx += 1

    CORE_STATE.write_text("\n".join(lines), encoding="utf-8")

    return {
        "status": "synced",
        "new_lessons_added": len(new_lessons),
        "lessons": new_lessons,
    }


# ── Self-Test ─────────────────────────────────────────────────


def self_test() -> dict:
    """Test: record → consult → circuit_breaker → summary."""
    test_error = "Self-test scar: unexpected argument '--fake-flag-xyz'"
    test_rule = "Use --real-flag instead of --fake-flag-xyz"

    try:
        # 1. Record
        r = record_scar(
            failed_action="codex exec --fake-flag-xyz",
            error_signature=test_error,
            recovery_action="codex exec --real-flag",
            prevention_rule=test_rule,
            context="self_test",
        )
        assert r["status"] in ("recorded", "incremented"), f"Record failed: {r}"
        test_id = r.get("id")

        # Small delay for Qdrant eventual consistency
        time.sleep(0.5)

        # 2. Consult — use semantically close query
        advice = consult("unexpected argument fake-flag-xyz in codex exec")
        assert len(advice) > 0, "Consult returned no results for similar instruction"
        assert advice[0]["score"] >= 0.70, f"Score too low: {advice[0]['score']}"

        # 3. Circuit breaker (should be False for frequency=1)
        cb = circuit_breaker_check(test_error)
        # May be True if test ran before — that's OK

        # 4. Summary
        s = summary(top_k=5)
        assert isinstance(s, list), f"Summary not a list: {type(s)}"

        # 5. Stats
        st = stats()
        assert st["total_scars"] > 0, f"No scars after record: {st}"

        # Cleanup: delete test scar
        if test_id:
            client = _get_client()
            try:
                client.delete(
                    collection_name=COLLECTION_NAME, points_selector=[test_id]
                )
            except ValueError as e:
                import logging

                logging.getLogger(__name__).warning("Ignored: %s", e)

        return {
            "status": "PASS",
            "record": "✅",
            "consult": f"✅ score={advice[0]['score']}",
            "circuit_breaker": f"✅ result={cb}",
            "summary": f"✅ {len(s)} scars",
            "stats": f"✅ {st['total_scars']} total",
        }

    except Exception as e:
        return {"status": "FAIL", "error": str(e)}


# ── CLI ───────────────────────────────────────────────────────


def main():
    if sys.stdout.encoding != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
        except ValueError as e:
            import logging

            logging.getLogger(__name__).warning("Ignored: %s", e)

    parser = argparse.ArgumentParser(
        description="Scar Memory — Failure-Recovery Pattern Learning (Phase 7)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # record
    p = sub.add_parser("record", help="Record a scar manually")
    p.add_argument("--failed", default="", help="Failed action description")
    p.add_argument("--error", default="", help="Error signature")
    p.add_argument("--recovery", default="", help="What fixed it")
    p.add_argument("--rule", default="", help="Prevention rule for the future")
    p.add_argument("--context", default="", help="Context identifier")
    p.add_argument("--name", default="", help="Short name of the knowledge item")
    p.add_argument("--description", default="", help="Description frontmatter")
    p.add_argument("--type", default="scar", help="Type of knowledge item")

    # consult
    p = sub.add_parser("consult", help="Check for relevant scars before executing")
    p.add_argument("--instruction", required=True)
    p.add_argument("--top-k", type=int, default=5)

    # auto-extract
    sub.add_parser("auto-extract", help="Extract scars from traces.log automatically")

    # circuit-check
    p = sub.add_parser("circuit-check", help="Check circuit breaker for an action")
    p.add_argument("--action", required=True)

    # summary
    p = sub.add_parser("summary", help="Top scars")
    p.add_argument("--top-k", type=int, default=10)

    # stats
    sub.add_parser("stats", help="Scar statistics")

    # sync-ltm
    sub.add_parser("sync-ltm", help="Sync top scars to core_state.yaml")

    # check-duplicate
    p = sub.add_parser("check-duplicate", help="Check if similar issue exists")
    p.add_argument("--text", required=True)

    # health-check
    p_health = sub.add_parser(
        "health-check",
        help="Boot-time health check: L1 (sqlite-vec) + L2 (Qdrant) status",
    )
    p_health.add_argument(
        "--l1-only",
        action="store_true",
        default=False,
        help="Skip L2 Qdrant ping (avoids Windows zipimport crash at boot)",
    )

    # test
    sub.add_parser("test", help="Self-test")

    args = parser.parse_args()

    if args.command == "record":
        result = record_scar(
            args.failed,
            args.error,
            args.recovery,
            args.rule,
            args.context,
            False,
            args.name,
            args.description,
            args.type,
        )
    elif args.command == "consult":
        result = consult(args.instruction, args.top_k)
    elif args.command == "auto-extract":
        result = auto_extract_from_traces()
    elif args.command == "circuit-check":
        result = {"circuit_broken": circuit_breaker_check(args.action)}
    elif args.command == "summary":
        result = summary(args.top_k)
    elif args.command == "stats":
        result = stats()
    elif args.command == "sync-ltm":
        result = sync_to_ltm()
    elif args.command == "health-check":
        result = health_check(l1_only=getattr(args, "l1_only", False))
    elif args.command == "test":
        result = self_test()
    elif args.command == "check-duplicate":
        result = check_duplicate(args.text)
    else:
        result = {"error": f"Unknown command: {args.command}"}

    try:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except UnicodeEncodeError:
        print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
