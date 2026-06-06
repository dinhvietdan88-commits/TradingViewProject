import os
import re


def find_project_root():
    current = os.path.dirname(os.path.abspath(__file__))
    while current and current != os.path.dirname(current):
        if os.path.exists(os.path.join(current, "PROJECT.md")):
            return current
        current = os.path.dirname(current)
    raise FileNotFoundError("Could not find project root containing PROJECT.md")


def test_parameter_matrix_integrity():
    """Verify that OPTIMIZED_PARAMETERS_MATRIX.md contains the exact required values for BTC, ETH, and SOL."""
    root = find_project_root()
    matrix_path = os.path.join(
        root, "docs", "knowledge", "trading_wizard", "OPTIMIZED_PARAMETERS_MATRIX.md"
    )
    assert os.path.exists(matrix_path), f"Parameters matrix not found at {matrix_path}"

    with open(matrix_path, encoding="utf-8") as f:
        content = f.read()

    # Check for BTC parameters
    assert "BTC" in content
    assert "8.0%" in content  # Hard SL BTC
    assert "1.0%" in content  # Risk per trade BTC
    assert "10.0%" in content  # Futures Pos Size BTC

    # Check for ETH parameters
    assert "ETH" in content
    assert "10.0%" in content  # Hard SL ETH
    assert "0.8%" in content  # Risk per trade ETH
    assert "8.0%" in content  # Futures Pos Size ETH

    # Check for SOL parameters
    assert "SOL" in content
    assert "13.0%" in content  # Hard SL SOL
    assert "0.6%" in content  # Risk per trade SOL
    assert "6.0%" in content  # Futures Pos Size SOL

    # Verify no placeholders remain
    assert "[TBD]" not in content, (
        "Found TBD placeholder in OPTIMIZED_PARAMETERS_MATRIX.md"
    )
    assert "placeholder" not in content.lower(), (
        "Found placeholder text in OPTIMIZED_PARAMETERS_MATRIX.md"
    )


def test_pine_script_lookahead_free():
    """Verify that minervini_strategy.pine implements lookahead-free MTF calculations correctly."""
    root = find_project_root()
    pine_path = os.path.join(root, "pine", "v2", "minervini_strategy.pine")
    assert os.path.exists(pine_path), f"Pine script not found at {pine_path}"

    with open(pine_path, encoding="utf-8") as f:
        content = f.read()

    # Look for request.security daily calls with lookahead_off and indexing offset [1]
    assert "request.security" in content
    assert '"D"' in content or "'D'" in content
    assert "barmerge.lookahead_off" in content

    # Verify strict lookahead-free offset pattern for daily EMAs
    pattern_20 = (
        r"request\.security\(.*ta\.ema\(close,\s*20\)\[1\].*barmerge\.lookahead_off\)"
    )
    pattern_50 = (
        r"request\.security\(.*ta\.ema\(close,\s*50\)\[1\].*barmerge\.lookahead_off\)"
    )
    pattern_100 = (
        r"request\.security\(.*ta\.ema\(close,\s*100\)\[1\].*barmerge\.lookahead_off\)"
    )

    # Clean up whitespace to prevent regex matching failures on formatting variations
    flat_content = re.sub(r"\s+", " ", content)
    assert re.search(pattern_20, flat_content) is not None, (
        "Daily EMA 20 request is not lookahead-free with [1] and lookahead_off"
    )
    assert re.search(pattern_50, flat_content) is not None, (
        "Daily EMA 50 request is not lookahead-free with [1] and lookahead_off"
    )
    assert re.search(pattern_100, flat_content) is not None, (
        "Daily EMA 100 request is not lookahead-free with [1] and lookahead_off"
    )

    # Check that is_mtt check is present to select between daily/local MAs
    assert "is_mtt" in content
    assert "daily_mf" in content
    assert "local_mf" in content
