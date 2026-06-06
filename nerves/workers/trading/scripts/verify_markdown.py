#!/usr/bin/env python3
"""
Verification script for WEEX API Markdown files.
Checks valid markdown structure (header nesting, local links, tables) and
ensures no placeholder text exists.
"""

import json
import os
import re
import sys

KI_DIR = r"c:/Users/pesil/working/mj_trading/TradingViewProject/lobes/knowledge/weex"
KI_FILES = [
    "weex_api_index.md",
    "weex_signatures_auth.md",
    "weex_spot_api_v1_v3.md",
    "weex_futures_usdt_m_api.md",
    "weex_futures_coin_m_api.md",
    "weex_copy_trading_api.md",
    "weex_websocket_channels.md",
    "weex_rate_limits_weights.md",
    "weex_market_data_announcements.md",
    "weex_sandbox_guide.md",
]


def verify_file(filepath):
    errors = []

    if not os.path.exists(filepath):
        errors.append(f"File {filepath} does not exist")
        return errors

    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    # 1. Placeholders check (case-insensitive)
    # Looking for word matches or bracket matches like [TBD], TODO, placeholder, draft, unfinished
    placeholders = ["tbd", "todo", "placeholder", "draft", "unfinished"]
    for ph in placeholders:
        pattern = re.compile(rf"\b{ph}\b|\[{ph}\]", re.IGNORECASE)
        matches = pattern.findall(content)
        if matches:
            errors.append(f"Placeholder detected: '{ph}' found {len(matches)} times")

    # 2. Header nesting check
    lines = content.splitlines()
    header_levels = []
    for line_num, line in enumerate(lines, 1):
        if line.strip().startswith("#"):
            match = re.match(r"^(#+)\s+(.*)$", line.strip())
            if match:
                level = len(match.group(1))
                header_levels.append((line_num, level))

    for i in range(1, len(header_levels)):
        prev_num, prev_lvl = header_levels[i - 1]
        curr_num, curr_lvl = header_levels[i]
        if curr_lvl > prev_lvl + 1:
            errors.append(
                f"Invalid header nesting at line {curr_num}: skipped from H{prev_lvl} to H{curr_lvl}"
            )

    # 3. Check for broken links
    link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    for line_num, line in enumerate(lines, 1):
        # Basic check for link syntax (skip comments or code examples if possible)
        if line.strip().startswith("`") or "```" in line:
            continue
        for _text, link in link_pattern.findall(line):
            # Skip external web and websocket URLs
            if (
                link.startswith("http://")
                or link.startswith("https://")
                or link.startswith("wss://")
            ):
                continue
            if link.startswith("#"):
                # Anchor within the same file
                anchor = link[1:]
                if not re.match(r"^[a-zA-Z0-9\-_]+$", anchor):
                    errors.append(
                        f"Malformed anchor link format at line {line_num}: {link}"
                    )
            else:
                # Local file link
                base_link = link.split("#")[0]
                if base_link not in KI_FILES:
                    errors.append(
                        f"Link referencing non-existent local file at line {line_num}: {link}"
                    )

    # 4. Valid tables check
    in_table = False
    table_cols = 0
    for line_num, line in enumerate(lines, 1):
        line_strip = line.strip()
        # Simple table detector
        if line_strip.startswith("|") and line_strip.endswith("|"):
            parts = [p.strip() for p in line_strip.split("|")]
            # Remove empty strings at start and end
            if parts and parts[0] == "":
                parts.pop(0)
            if parts and parts[-1] == "":
                parts.pop()

            part_count = len(parts)

            # Check for separator row (e.g. |---| or |:---|)
            is_separator = all(re.match(r"^:?\-+:?$", p) for p in parts)

            if not in_table:
                in_table = True
                table_cols = part_count
            else:
                if is_separator:
                    continue
                if part_count != table_cols:
                    errors.append(
                        f"Table column mismatch at line {line_num}: expected {table_cols} columns, got {part_count}"
                    )
        else:
            in_table = False

    return errors


def run_verification():
    report = {"status": "success", "total_files": len(KI_FILES), "files": {}}

    overall_success = True

    for filename in KI_FILES:
        filepath = os.path.join(KI_DIR, filename)
        errors = verify_file(filepath)
        if errors:
            overall_success = False
            report["files"][filename] = {"status": "failed", "errors": errors}
        else:
            report["files"][filename] = {"status": "passed", "errors": []}

    if not overall_success:
        report["status"] = "failed"

    # Write report
    os.makedirs(KI_DIR, exist_ok=True)
    report_path = os.path.join(KI_DIR, "verification_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(json.dumps(report, indent=2))

    return overall_success


if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
