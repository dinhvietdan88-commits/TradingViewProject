import subprocess
import sys


# Configure stdout to use UTF-8 to prevent encoding issues on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def run_cmd(cmd):
    try:
        res = subprocess.run(  # noqa: S602
            cmd, shell=True, text=True, capture_output=True, check=True
        )
        return res.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running command '{cmd}': {e.stderr.strip()}")
        return None


def check_branch_tiers():
    print("--- Angati CI/CD Branch Check ---")

    # 1. Fetch latest changes
    print("Fetching remote updates...")
    run_cmd("git fetch")

    # 2. Get status / branch differences
    status = run_cmd("git status -s")
    print(f"Local modifications:\n{status if status else 'None'}\n")

    # Check if we are behind or ahead
    branch_status = run_cmd("git status")
    print("Branch status summary:")
    if "Your branch is behind" in branch_status:
        print("⚠️ Warning: Local branch is BEHIND origin. Needs pull.")
    elif "Your branch is ahead" in branch_status:
        print("ℹ️ Info: Local branch is AHEAD of origin. Needs push.")
    else:
        print("✅ Local branch is up-to-date with origin.")

    # 3. Analyze changes to determine deploy Tier
    # Let's get files changed in git status (local changes) + diff with origin
    changed_files = []

    # Local untracked & modified
    lines = status.split("\n") if status else []
    for line in lines:
        if line.strip():
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                changed_files.append(parts[1])

    # Diff with origin/main to see what is new on origin if we are behind
    diff_origin = run_cmd("git diff --name-only HEAD..origin/main")
    if diff_origin:
        changed_files.extend(diff_origin.split("\n"))

    # Remove duplicates and empty strings
    changed_files = list(set(filter(None, changed_files)))

    if not changed_files:
        print("\nTier Assessment: T0 (Skip - No changes detected)")
        return

    print(f"Detected changed files ({len(changed_files)}):")
    for f in changed_files:
        print(f" - {f}")

    # Tier classification logic
    tier = "T0"
    reasons = []

    for f in changed_files:
        # Check source code / Docker / Python files
        if (
            f.endswith(".py")
            or f.endswith(".html")
            or f.endswith(".js")
            or f.endswith("Dockerfile")
            or "nerves/" in f
        ) and "tests/" not in f:
            tier = "T2"
            reasons.append(f"{f} (Source/Logic/UI)")
            break  # T2 is highest, no need to check further

        elif (
            f.endswith(".yaml")
            or f.endswith(".json")
            or "config" in f
            or "deploy/" in f
        ):
            if tier != "T2":
                tier = "T1"
                reasons.append(f"{f} (Config/Deploy)")

        else:
            if tier not in ["T1", "T2"]:
                tier = "T0"
                reasons.append(f"{f} (Docs/Tests/CI)")

    print(f"\nRecommended Action: {tier}")
    if tier == "T2":
        print(
            "👉 Tier 2: docker pull + docker up -d required due to: "
            + ", ".join(reasons[:3])
        )
    elif tier == "T1":
        print(
            "👉 Tier 1: git pull + docker restart required due to: "
            + ", ".join(reasons[:3])
        )
    else:
        print(
            "👉 Tier 0: Skip deploy (only docs, tests, or CI configurations changed) due to: "
            + ", ".join(reasons[:3])
        )


if __name__ == "__main__":
    check_branch_tiers()
