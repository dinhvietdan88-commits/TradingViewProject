#!/usr/bin/env python3
"""
ADK Evaluation Metrics — Agent Quality Assurance

Implements 3 evaluation metrics inspired by Google ADK's AgentEvaluator:
    1. Tool Trajectory Score — validates tool usage sequence
    2. Response Quality Score — ROUGE-1 based lexical overlap
    3. Scar Regression Check — ensures known scars don't recur

These metrics extend the existing angati-core-qa skill with
ADK-standard quality dimensions.

Isomorphism:
    ADK tool_trajectory_avg_score  ↔  tool_trajectory_score()
    ADK response_match_score       ↔  response_quality_score()
    ADK hallucinations_v1          ↔  scar_regression_check()

References:
    - KI: google-adk-deep-research §10 (Evaluation Framework)
    - Skill: angati-core-qa (existing QA pipeline)
"""

import re
from collections import Counter


# ---------------------------------------------------------------------------
# Metric 1: Tool Trajectory Score
# ---------------------------------------------------------------------------


def tool_trajectory_score(
    expected: list[str], actual: list[str], match_type: str = "IN_ORDER"
) -> float:
    """
    Score tool usage trajectory against expected sequence.

    Validates that the agent used the correct tools in the correct order.
    This is the Angati equivalent of ADK's tool_trajectory_avg_score.

    Args:
        expected: Expected sequence of tool names (the "golden" trajectory)
        actual: Actual sequence of tool names used by the agent
        match_type: One of:
            - "EXACT": Requires exact sequence match (tools and order)
            - "IN_ORDER": Expected tools must appear in order (other tools allowed)
            - "ANY_ORDER": Expected tools must all appear (any order)

    Returns:
        float: Score between 0.0 and 1.0

    Examples:
        >>> tool_trajectory_score(["search", "write"], ["search", "read", "write"], "IN_ORDER")
        1.0
        >>> tool_trajectory_score(["search", "write"], ["write", "search"], "EXACT")
        0.0
        >>> tool_trajectory_score(["search", "write"], ["write", "search"], "ANY_ORDER")
        1.0
    """
    if not expected:
        return 1.0 if not actual else 0.0

    if match_type == "EXACT":
        return 1.0 if expected == actual else 0.0

    elif match_type == "IN_ORDER":
        # Check if expected tools appear in order within actual
        expected_idx = 0
        for tool in actual:
            if expected_idx < len(expected) and tool == expected[expected_idx]:
                expected_idx += 1
        return expected_idx / len(expected)

    elif match_type == "ANY_ORDER":
        # Check if all expected tools appear in actual (any order)
        actual_set = set(actual)
        matches = sum(1 for t in expected if t in actual_set)
        return matches / len(expected)

    else:
        raise ValueError(
            f"Unknown match_type: {match_type}. Use EXACT, IN_ORDER, or ANY_ORDER"
        )


# ---------------------------------------------------------------------------
# Metric 2: Response Quality Score (ROUGE-1)
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    text = text.lower().strip()
    # Split on whitespace and remove empty tokens
    tokens = re.findall(r"\b\w+\b", text)
    return tokens


def response_quality_score(reference: str, candidate: str) -> float:
    """
    ROUGE-1 based response quality metric.

    Computes the F1 score of unigram overlap between reference and candidate.
    This is the Angati equivalent of ADK's response_match_score (ROUGE-1).

    Args:
        reference: The expected/golden response text
        candidate: The actual agent response text

    Returns:
        float: ROUGE-1 F1 score between 0.0 and 1.0

    Examples:
        >>> response_quality_score("the cat sat on the mat", "the cat sat on the mat")
        1.0
        >>> response_quality_score("hello world", "goodbye world")
        0.5
    """
    if not reference and not candidate:
        return 1.0
    if not reference or not candidate:
        return 0.0

    ref_tokens = _tokenize(reference)
    cand_tokens = _tokenize(candidate)

    if not ref_tokens or not cand_tokens:
        return 0.0

    ref_counts = Counter(ref_tokens)
    cand_counts = Counter(cand_tokens)

    # Count overlapping tokens (intersection of multisets)
    overlap = 0
    for token, count in ref_counts.items():
        overlap += min(count, cand_counts.get(token, 0))

    precision = overlap / len(cand_tokens) if cand_tokens else 0.0
    recall = overlap / len(ref_tokens) if ref_tokens else 0.0

    if precision + recall == 0:
        return 0.0

    f1 = 2 * (precision * recall) / (precision + recall)
    return round(f1, 4)


# ---------------------------------------------------------------------------
# Metric 3: Scar Regression Check
# ---------------------------------------------------------------------------


def scar_regression_check(
    scar_patterns: list[dict], test_output: str, test_logs: str = ""
) -> dict:
    """
    Check if known scars have regressed.

    Validates that previously-fixed failure patterns (scars) don't recur
    in the current test output. This is the Angati equivalent of ADK's
    hallucinations_v1 metric — ensuring the system doesn't repeat
    known mistakes.

    Args:
        scar_patterns: List of scar pattern dicts, each with:
            - id: Scar identifier (e.g., "SCAR-001")
            - pattern: Regex pattern that indicates regression
            - description: Human-readable scar description
        test_output: The test execution output to check
        test_logs: Additional log output to check (optional)

    Returns:
        dict with:
            - passed: bool (True if no regressions found)
            - score: float (1.0 = all clear, 0.0 = all regressed)
            - regressions: List of regressed scar IDs
            - details: List of detailed regression info

    Examples:
        >>> scar_regression_check(
        ...     [{"id": "SCAR-001", "pattern": "CommandNotFoundException", "description": "MCP vs Terminal"}],
        ...     "All tests passed"
        ... )
        {'passed': True, 'score': 1.0, 'regressions': [], 'details': []}
    """
    if not scar_patterns:
        return {"passed": True, "score": 1.0, "regressions": [], "details": []}

    combined_output = f"{test_output}\n{test_logs}"
    regressions = []
    details = []

    for scar in scar_patterns:
        scar_id = scar.get("id", "UNKNOWN")
        pattern = scar.get("pattern", "")
        description = scar.get("description", "")

        if not pattern:
            continue

        try:
            if re.search(pattern, combined_output, re.IGNORECASE):
                regressions.append(scar_id)
                details.append(
                    {
                        "scar_id": scar_id,
                        "pattern": pattern,
                        "description": description,
                        "status": "REGRESSED",
                    }
                )
        except re.error:
            # Invalid regex pattern — skip but log
            details.append(
                {
                    "scar_id": scar_id,
                    "pattern": pattern,
                    "description": description,
                    "status": "PATTERN_ERROR",
                }
            )

    total = len(scar_patterns)
    passed_count = total - len(regressions)
    score = passed_count / total if total > 0 else 1.0

    return {
        "passed": len(regressions) == 0,
        "score": round(score, 4),
        "regressions": regressions,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Composite Evaluation
# ---------------------------------------------------------------------------


def evaluate_agent_run(
    expected_trajectory: list[str] = None,
    actual_trajectory: list[str] = None,
    reference_response: str = None,
    actual_response: str = None,
    scar_patterns: list[dict] = None,
    test_output: str = "",
    thresholds: dict = None,
) -> dict:
    """
    Run all evaluation metrics and compare against thresholds.

    This is the Angati equivalent of ADK's AgentEvaluator. It runs
    all configured metrics and produces a pass/fail verdict.

    Args:
        expected_trajectory: Expected tool sequence
        actual_trajectory: Actual tool sequence
        reference_response: Golden reference response
        actual_response: Agent's actual response
        scar_patterns: List of scar patterns to check
        test_output: Test execution output for scar regression
        thresholds: Dict of metric_name → minimum_score

    Returns:
        dict with overall verdict and individual metric results
    """
    if thresholds is None:
        thresholds = {
            "tool_trajectory_avg_score": 0.8,
            "response_quality_score": 0.7,
            "scar_regression_pass": 1.0,
        }

    results = {}
    all_passed = True

    # Metric 1: Tool Trajectory
    if expected_trajectory is not None and actual_trajectory is not None:
        score = tool_trajectory_score(
            expected_trajectory, actual_trajectory, "IN_ORDER"
        )
        threshold = thresholds.get("tool_trajectory_avg_score", 0.8)
        passed = score >= threshold
        results["tool_trajectory"] = {
            "score": score,
            "threshold": threshold,
            "passed": passed,
        }
        if not passed:
            all_passed = False

    # Metric 2: Response Quality
    if reference_response is not None and actual_response is not None:
        score = response_quality_score(reference_response, actual_response)
        threshold = thresholds.get("response_quality_score", 0.7)
        passed = score >= threshold
        results["response_quality"] = {
            "score": score,
            "threshold": threshold,
            "passed": passed,
        }
        if not passed:
            all_passed = False

    # Metric 3: Scar Regression
    if scar_patterns is not None:
        scar_result = scar_regression_check(scar_patterns, test_output)
        threshold = thresholds.get("scar_regression_pass", 1.0)
        passed = scar_result["score"] >= threshold
        results["scar_regression"] = {
            "score": scar_result["score"],
            "threshold": threshold,
            "passed": scar_result["passed"],
            "regressions": scar_result["regressions"],
        }
        if not passed:
            all_passed = False

    import time
    return {
        "overall_passed": all_passed,
        "metrics": results,
        "timestamp": time.time(),
    }
