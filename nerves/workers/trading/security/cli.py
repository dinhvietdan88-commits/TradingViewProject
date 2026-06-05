"""
Mini-MDASH CLI — Command-line interface for security scanning.

Usage:
  # Full scan with Markdown report
  python -m security.cli scan --target ./server

  # Scan with JSON output (for CI/CD)
  python -m security.cli scan --target ./server --format json

  # CI mode (exit code 1 on critical findings)
  python -m security.cli scan --target ./server --ci --fail-on critical

  # Exclude specific rules
  python -m security.cli scan --target ./server --exclude TVP-006,STA-004
"""

import argparse
import logging
import sys
from pathlib import Path


def main():
    # Fix Windows cp1252 encoding for emoji in report output
    import io

    if sys.stdout and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
    if sys.stderr and hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace"
        )

    parser = argparse.ArgumentParser(
        prog="mini-mdash",
        description="Mini-MDASH: Agentic Security Harness for Trading Systems",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # scan command
    scan_parser = subparsers.add_parser("scan", help="Run security scan")
    scan_parser.add_argument(
        "--target",
        "-t",
        default=".",
        help="Target directory to scan (default: current directory)",
    )
    scan_parser.add_argument(
        "--format",
        "-f",
        choices=["markdown", "json", "telegram"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    scan_parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output file path (default: stdout)",
    )
    scan_parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: set exit code based on findings",
    )
    scan_parser.add_argument(
        "--fail-on",
        choices=["critical", "high", "medium", "low"],
        default="critical",
        help="Severity threshold for CI failure (default: critical)",
    )
    scan_parser.add_argument(
        "--exclude",
        default="",
        help="Comma-separated rule IDs to exclude (e.g., TVP-006,STA-004)",
    )
    scan_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose logging",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "scan":
        _run_scan(args)


def _run_scan(args):
    """Execute the scan pipeline."""
    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-5s  %(message)s",
        stream=sys.stderr,  # Log to stderr, report to stdout
    )

    # Resolve target
    target = Path(args.target).resolve()
    if not target.exists():
        print(f"Error: Target directory not found: {target}", file=sys.stderr)
        sys.exit(2)

    # Parse excluded rules
    exclude = (
        [r.strip() for r in args.exclude.split(",") if r.strip()]
        if args.exclude
        else []
    )

    # Import here to avoid circular imports at CLI parse time
    from security.harness import SecurityHarness
    from security import report as report_mod

    # Run pipeline
    harness = SecurityHarness(str(target), exclude_rules=exclude)
    security_report = harness.run()

    # Generate output
    if args.format == "json":
        output = report_mod.to_json(security_report)
    elif args.format == "telegram":
        output = report_mod.to_telegram(security_report)
    else:
        output = report_mod.to_markdown(security_report)

    # Write output
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(output, encoding="utf-8")
        print(f"Report written to {output_path}", file=sys.stderr)
    else:
        print(output)

    # CI exit code
    if args.ci:
        from security import Severity

        threshold_map = {
            "critical": Severity.CRITICAL,
            "high": Severity.HIGH,
            "medium": Severity.MEDIUM,
            "low": Severity.LOW,
        }
        threshold = threshold_map[args.fail_on]
        severity_rank = {
            Severity.CRITICAL: 0,
            Severity.HIGH: 1,
            Severity.MEDIUM: 2,
            Severity.LOW: 3,
            Severity.INFO: 4,
        }
        threshold_rank = severity_rank[threshold]

        failing = [
            f
            for f in security_report.findings
            if severity_rank.get(f.severity, 99) <= threshold_rank
        ]
        if failing:
            print(
                f"\nCI FAIL: {len(failing)} findings at or above {args.fail_on} severity",
                file=sys.stderr,
            )
            sys.exit(1)
        else:
            print(
                f"\nCI PASS: No findings at or above {args.fail_on} severity",
                file=sys.stderr,
            )
            sys.exit(0)


if __name__ == "__main__":
    main()
