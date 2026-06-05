---
name: adk-eval-metrics
description: >
  ADK Evaluation Metrics integration for angati-core-qa.
  Extends the existing QA pipeline with 3 Google ADK-compatible
  evaluation dimensions: Tool Trajectory Score, Response Quality
  (ROUGE-1), and Scar Regression Check.
---

# ADK Evaluation Metrics

## Overview

This skill extends the existing `angati-core-qa` skill with evaluation
metrics inspired by Google's Agent Development Kit (ADK) `AgentEvaluator`.

## Metrics

### 1. Tool Trajectory Score
Validates that the agent used the correct tools in the correct order.

```python
from nerves.core.eval_metrics import tool_trajectory_score

score = tool_trajectory_score(
    expected=["grep_search", "view_file", "replace_file_content"],
    actual=["grep_search", "list_dir", "view_file", "replace_file_content"],
    match_type="IN_ORDER"  # EXACT | IN_ORDER | ANY_ORDER
)
# score = 1.0 (all expected tools appear in order)
```

### 2. Response Quality Score (ROUGE-1)
Measures lexical overlap between reference and actual responses.

```python
from nerves.core.eval_metrics import response_quality_score

score = response_quality_score(
    reference="The SMA crossover indicates a bullish trend",
    candidate="SMA crossover shows bullish momentum in the trend"
)
# score ≈ 0.67 (ROUGE-1 F1)
```

### 3. Scar Regression Check
Ensures previously-fixed failure patterns don't recur.

```python
from nerves.core.eval_metrics import scar_regression_check

result = scar_regression_check(
    scar_patterns=[
        {"id": "SCAR-001", "pattern": "CommandNotFoundException", "description": "MCP vs Terminal"}
    ],
    test_output="All tests passed successfully"
)
# result = {"passed": True, "score": 1.0, "regressions": []}
```

## Composite Evaluation

Run all metrics at once with threshold checking:

```python
from nerves.core.eval_metrics import evaluate_agent_run

result = evaluate_agent_run(
    expected_trajectory=["search", "analyze", "execute"],
    actual_trajectory=["search", "analyze", "execute"],
    reference_response="Trade executed successfully",
    actual_response="Trade was executed with success",
    scar_patterns=[...],
    test_output="...",
    thresholds={
        "tool_trajectory_avg_score": 0.8,
        "response_quality_score": 0.7,
        "scar_regression_pass": 1.0
    }
)
print(result["overall_passed"])  # True/False
```

## Configuration

Thresholds are defined in `nerves/core/test_config.json`.

## Dependencies

- No external dependencies (pure Python stdlib)
- Optional: ChromaDB for memory bridge integration

## References

- KI: `google-adk-deep-research` §10 (Evaluation Framework)
- KI: `harness-taxonomy-mdash-aqh` (Harness Taxonomy)
- Skill: `angati-core-qa` (extended by this skill, including `harness-light` and `harness-full` modes)
- Bridge: `nerves/core/harness_bridge.py` (wires eval_metrics into AQH MDASH pipeline)
