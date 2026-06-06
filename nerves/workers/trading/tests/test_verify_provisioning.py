import os
import re
import sys
from unittest.mock import patch

# Add scripts directory to sys.path
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts"))
)
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../scripts"))
)

import verify_provisioning


def test_natural_sort_key():
    """Verify natural numeric sorting key."""
    # Test individual key generation
    assert verify_provisioning.natural_sort_key(("11.1.2", None)) == [11, 1, 2]
    assert verify_provisioning.natural_sort_key(("11.1.10", None)) == [11, 1, 10]
    assert verify_provisioning.natural_sort_key(("11.2.1", None)) == [11, 2, 1]

    # Test sorting behavior
    items = [
        ("11.1.10", "ten"),
        ("11.1.2", "two"),
        ("11.2.1", "one_sec_two"),
        ("11.1.1", "one"),
    ]
    sorted_items = sorted(items, key=verify_provisioning.natural_sort_key)
    expected = [
        ("11.1.1", "one"),
        ("11.1.2", "two"),
        ("11.1.10", "ten"),
        ("11.2.1", "one_sec_two"),
    ]
    assert sorted_items == expected


def test_is_ssh_connection_failure():
    """Verify robust SSH connection failure detection."""
    # Standard exit codes indicating connection/auth issues
    assert verify_provisioning.is_ssh_connection_failure(255, "", "") is True
    assert verify_provisioning.is_ssh_connection_failure(-1, "", "") is True
    assert verify_provisioning.is_ssh_connection_failure(-2, "", "") is True
    assert verify_provisioning.is_ssh_connection_failure(-3, "", "") is True

    # Standard connection strings in stderr
    assert (
        verify_provisioning.is_ssh_connection_failure(
            1, "", "Permission denied (publickey)."
        )
        is True
    )
    assert (
        verify_provisioning.is_ssh_connection_failure(1, "", "Connection timed out")
        is True
    )
    assert (
        verify_provisioning.is_ssh_connection_failure(
            1, "", "ssh: connect to host 1.2.3.4 port 22: Connection refused"
        )
        is True
    )

    # Exit code 0 should not be a connection failure even if some warning occurs
    assert verify_provisioning.is_ssh_connection_failure(0, "some output", "") is False

    # Command successfully executed but printed a permission error (e.g. file permissions)
    # This should NOT be detected as an SSH connection failure.
    assert (
        verify_provisioning.is_ssh_connection_failure(
            1, "", "bash: /opt/trading-bot/.env: Permission denied"
        )
        is False
    )
    assert (
        verify_provisioning.is_ssh_connection_failure(126, "", "Permission denied")
        is False
    )


@patch("verify_provisioning.run_ssh_command")
def test_ssh_conn_fallback_success(mock_run):
    """Verify that SSHConn falls back to botuser when root connection fails and fallback succeeds."""
    conn = verify_provisioning.SSHConn("Server A", "1.2.3.4", "root", "key.pem")

    # First call (root) fails with connection/auth error.
    # Second call (botuser) succeeds.
    mock_run.side_effect = [
        (255, "", "Permission denied (publickey)."),  # Primary (root) fails
        (0, "success_output", ""),  # Fallback (botuser) succeeds
    ]

    code, out, err = conn.run("ls -la")

    assert code == 0
    assert out == "success_output"
    assert conn.user == "botuser"
    assert conn.connection_failed is False
    assert mock_run.call_count == 2
    mock_run.assert_any_call("1.2.3.4", "root", "key.pem", "ls -la")
    mock_run.assert_any_call("1.2.3.4", "botuser", "key.pem", "ls -la")


@patch("verify_provisioning.run_ssh_command")
def test_ssh_conn_fallback_failure(mock_run):
    """Verify that SSHConn does not mutate user and caches failure when fallback also fails connection."""
    conn = verify_provisioning.SSHConn("Server A", "1.2.3.4", "root", "key.pem")

    # First call (root) fails.
    # Second call (botuser) also fails.
    mock_run.side_effect = [
        (255, "", "Permission denied (publickey)."),  # Primary (root) fails
        (255, "", "Connection timed out"),  # Fallback (botuser) fails
    ]

    code, out, err = conn.run("ls -la")

    assert code == 255
    assert conn.user == "root"  # Should NOT be mutated
    assert conn.connection_failed is True
    assert mock_run.call_count == 2


@patch("verify_provisioning.run_ssh_command")
def test_ssh_conn_caching_and_fail_fast(mock_run):
    """Verify that connection failure is cached and subsequent run calls fail fast."""
    conn = verify_provisioning.SSHConn("Server A", "1.2.3.4", "root", "key.pem")
    conn.connection_failed = True

    code, out, err = conn.run("ls -la")

    assert code == -3
    assert "cached connection failure" in err
    # Should not invoke run_ssh_command at all
    mock_run.assert_not_called()


def test_auto_tick_logic():
    """Test auto-tick logic behaviour under different pass/fail/skip scenarios."""
    results = {
        "11.1.1": {"passed": True},
        "11.1.2": {"passed": False},
        "11.1.3": {"passed": True},
    }

    # Helper function mock-tick simulation based on verify_provisioning.py logic
    def simulate_ticking(lines, results_dict):
        new_lines = []
        current_section = None
        for line in lines:
            stripped = line.strip()
            if "### 11.1" in stripped:
                current_section = "11.1"
            elif stripped.startswith("## ") or (
                stripped.startswith("### ")
                and not any(sec in stripped for sec in ["11.1"])
            ):
                current_section = None

            if current_section and line.startswith("|"):
                match = re.match(r"^\|\s*(\d+)\s*\|([^|]+)\|\s*([☐☑])\s*\|", stripped)
                if match:
                    num = int(match.group(1))
                    key = f"{current_section}.{num}"
                    if key in results_dict and results_dict[key]["passed"]:
                        parts = line.split("|")
                        if len(parts) >= 4:
                            parts[-2] = " ☑ "
                            line = "|".join(parts)
            new_lines.append(line)
        return new_lines

    # Input markdown lines
    markdown_content = [
        "### 11.1 SERVER A",
        "| # | Hạng mục | Trạng thái |",
        "|---|----------|-----------|",
        "| 1 | Debian 12 Minimal đã cài | ☐ |",
        "| 2 | apt update && apt upgrade | ☑ |",  # Previously ticked but now failed
        "| 3 | User botuser | ☐ |",
        "| 4 | Non-existent check | ☑ |",  # Previously ticked but not in current run results
    ]

    updated_lines = simulate_ticking(markdown_content, results)

    # 1. passed=True should change ☐ to ☑
    assert "Debian 12 Minimal đã cài | ☑ |" in updated_lines[3]

    # 2. passed=False should keep the existing ☑ (unmodified)
    assert "apt update && apt upgrade | ☑ |" in updated_lines[4]

    # 3. passed=True should change ☐ to ☑
    assert "User botuser | ☑ |" in updated_lines[5]

    # 4. skipped/missing check should keep the existing ☑ (unmodified)
    assert "Non-existent check | ☑ |" in updated_lines[6]
