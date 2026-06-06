#!/usr/bin/env python3
"""
git-commit-organizer.py
An interactive CLI utility to group, review, and commit changes following Conventional Commits guidelines.
Designed for the TradingView Automation & Bot ecosystem.
"""

import os
import re
import subprocess
import sys
import tempfile

# Terminal Styling (ANSI Colors)
RESET = "\033[0m"
BOLD = "\033[1m"
UNDERLINE = "\033[4m"

# Colors
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

# Backgrounds
BG_DARK = "\033[40m"

# Reconfigure output to support UTF-8 on Windows if supported
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")  # noqa: S605


def print_header(title):
    print(f"\n{BOLD}{CYAN}>>> {title} <<<{RESET}")
    print(f"{CYAN}{'=' * (len(title) + 8)}{RESET}\n")


def get_git_status():
    """Returns a list of tuples containing (status, file_path) from git status --porcelain."""
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        )
        lines = res.stdout.strip().split("\n")
        files = []
        for line in lines:
            if not line.strip():
                continue
            # Format is usually: XY path or XY "path"
            status = line[:2]
            path = line[2:].strip().strip('"')
            files.append((status, path))
        return files
    except subprocess.CalledProcessError as e:
        print(f"{RED}Error running git status: {e}{RESET}")
        return []


# Category configuration
CATEGORIES = {
    "pine": {
        "name": "Pine Script Strategy Updates",
        "patterns": [r"^pine/"],
        "default_type": "feat",
        "scope": "pine",
        "description": "Pine Script indicator, strategy, MTF calculations, and webhook payload logic.",
    },
    "bot": {
        "name": "Telegram Bot & Signals Interface",
        "patterns": [
            r"telegram_bot\.py$",
            r"brief\.py$",
            r"symbol_config\.py$",
            r"alert_manager\.py$",
        ],
        "default_type": "feat",
        "scope": "bot",
        "description": "Telegram bot commands, daily brief formatter, alert signaling, and interactive approval flows.",
    },
    "webhook": {
        "name": "Webhook Ingress & Analysis Engine",
        "patterns": [
            r"analysis\.py$",
            r"mcp_client\.py$",
            r"binance_client\.py$",
            r"main\.py$",
            r"processor/",
            r"gateway/",
            r"data/",
            r"utils/",
        ],
        "default_type": "feat",
        "scope": "webhook",
        "description": "FastAPI ingress, rate limiters, AI market regime filters, and CDP browser automation.",
    },
    "docs": {
        "name": "Documentation & References",
        "patterns": [r"^docs/", r"\.md$"],
        "default_type": "docs",
        "scope": "knowledge",
        "description": "Optimized parameters matrices, strategy genealogy logs, and reference architectures.",
    },
    "test": {
        "name": "Test Suites & Harnesses",
        "patterns": [r"tests/", r"test_.*\.py$"],
        "default_type": "test",
        "scope": "unit",
        "description": "Adversarial tests, unit tests, and integration test scenarios.",
    },
    "chore": {
        "name": "Workspace Configuration & Maintenance",
        "patterns": [
            r"^\.gitignore$",
            r"^\.env",
            r"^scratch/",
            r"^scripts/",
            r"ORIGINAL_REQUEST.md",
        ],
        "default_type": "chore",
        "scope": "git",
        "description": "Ignore updates, build scripts, workspace properties, and sandbox files.",
    },
}


def identify_category(file_path):
    """Categorize file based on pattern matching."""
    # Normalize path separators
    normalized_path = file_path.replace("\\", "/")
    for cat_id, info in CATEGORIES.items():
        for pattern in info["patterns"]:
            if re.search(pattern, normalized_path):
                return cat_id
    return "other"


def group_changes(files):
    """Groups status items into categories."""
    groups = {cat: [] for cat in CATEGORIES.keys()}
    groups["other"] = []

    for status, path in files:
        cat = identify_category(path)
        groups[cat].append((status, path))
    return groups


def generate_message_suggestion(cat_id, files_list):
    """Generate Conventional Commit message based on category and changed files."""
    if not files_list:
        return ""

    info = CATEGORIES.get(cat_id, {"default_type": "chore", "scope": "workspace"})

    prefix = f"{info['default_type']}({info['scope']}):"

    # Analyze the files to suggest something specific
    basenames = [os.path.basename(f[1]) for f in files_list]

    if cat_id == "pine":
        if any("minervini" in b for b in basenames):
            return (
                f"{prefix} upgrade strategy to support lookahead-free MTF calculations"
            )
        return f"{prefix} update pine script strategies"
    elif cat_id == "docs":
        if any("OPTIMIZED" in b for b in basenames):
            return f"{prefix} compile central optimized parameters matrix and updates"
        if any("GENEALOGY" in b for b in basenames):
            return f"{prefix} update strategy genealogy performance logs"
        return f"{prefix} update project reference documentation"
    elif cat_id == "bot":
        parts = []
        if any("telegram_bot" in b for b in basenames):
            parts.append("telegram bot commands")
        if any("brief" in b for b in basenames):
            parts.append("brief formatting")
        description = (
            " and ".join(parts) if parts else "bot controls and interface files"
        )
        return f"{prefix} enhance {description}"
    elif cat_id == "webhook":
        if any("mcp_client" in b for b in basenames):
            return f"{prefix} optimize concurrency semaphore and request processing"
        if any("analysis" in b for b in basenames):
            return f"{prefix} implement trend/chop market regime filters"
        return f"{prefix} update webhook handler logic"
    elif cat_id == "test":
        if any("scan_all" in b for b in basenames):
            return f"{prefix} add stress tests for dynamic symbol scanner"
        if any("bot" in b for b in basenames):
            return f"{prefix} verify telegram bot message life cycle"
        return f"{prefix} expand unit and integration test coverage"
    elif cat_id == "chore":
        if ".gitignore" in basenames:
            return f"{prefix} ignore server/ junction and format config file"
        return f"{prefix} clean up workspace properties and logs"

    return f"chore(workspace): update {', '.join(basenames[:2])}"


def run_tests():
    """Runs tests to verify integrity before committing."""
    print(f"\n{BOLD}{YELLOW}Running test suite verifying stability...{RESET}")
    # We run pytest from server/ since that is the configured testing command in AGENTS.md
    res = subprocess.run(["python", "-m", "pytest"], capture_output=False)
    if res.returncode == 0:
        print(f"\n{BOLD}{GREEN}✅ All tests PASSED successfully!{RESET}")
        return True
    else:
        print(
            f"\n{BOLD}{RED}❌ Some tests FAILED. Please review test failures before committing.{RESET}"
        )
        return False


def edit_commit_message(initial_msg):
    """Allows user to edit the commit message in a temp file via default editor."""
    editor = os.environ.get(
        "EDITOR", os.environ.get("VISUAL", "notepad" if os.name == "nt" else "nano")
    )
    with tempfile.NamedTemporaryFile(
        suffix=".tmp", delete=False, mode="w", encoding="utf-8"
    ) as tf:
        tf.write(initial_msg)
        temp_name = tf.name

    try:
        subprocess.run([editor, temp_name], check=True)
        with open(temp_name, "r", encoding="utf-8") as f:
            edited_msg = f.read().strip()
        return edited_msg
    except Exception as e:
        print(f"{RED}Failed to open editor '{editor}': {e}. Prefilling default.{RESET}")
        user_input = input(f"Edit commit message: [{initial_msg}]: ").strip()
        return user_input if user_input else initial_msg
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def stage_and_commit(cat_id, files_list):
    """Stages specific files in a category and commits them with a Conventional message."""
    print_header(f"Committing {CATEGORIES.get(cat_id, {'name': cat_id})['name']}")

    # 1. Show files
    print(f"{BOLD}Files to stage and commit:{RESET}")
    for status, path in files_list:
        print(f"  {YELLOW}{status}{RESET} {path}")
    print()

    # 2. Get message suggestion
    suggestion = generate_message_suggestion(cat_id, files_list)
    print(f"{BOLD}Suggested message:{RESET} {GREEN}{suggestion}{RESET}\n")

    choice = (
        input(
            "Do you want to: [C]ommit with suggestion, [E]dit message, or [A]bort? [C/e/a]: "
        )
        .strip()
        .lower()
    )
    if choice == "a":
        print(f"{YELLOW}Skipped committing this group.{RESET}")
        return False

    final_msg = suggestion
    if choice == "e":
        final_msg = edit_commit_message(suggestion)
        if not final_msg:
            print(f"{RED}Empty commit message. Aborting commit.{RESET}")
            return False

    print(f"\n{BOLD}Executing Git commands...{RESET}")

    # Stage files
    for _, path in files_list:
        subprocess.run(["git", "add", path], check=True)
        print(f"  Staged: {path}")

    # Commit
    res = subprocess.run(
        ["git", "commit", "-m", final_msg], capture_output=True, text=True
    )
    if res.returncode == 0:
        print(f"\n{BOLD}{GREEN}✅ Successfully committed changes!{RESET}")
        print(f"{CYAN}{res.stdout.strip()}{RESET}")
        return True
    else:
        print(f"\n{BOLD}{RED}❌ Git commit failed!{RESET}")
        print(f"{RED}{res.stderr.strip()}{RESET}")
        # Unstage files just in case
        for _, path in files_list:
            subprocess.run(["git", "restore", "--staged", path])
        return False


def show_diff(cat_id, files_list):
    """Shows git diff for files in a specific category."""
    print_header(f"Diff for {CATEGORIES.get(cat_id, {'name': cat_id})['name']}")
    paths = [f[1] for f in files_list]

    # Run git diff for each file
    subprocess.run(["git", "diff"] + paths)
    input("\nPress Enter to return to the menu...")


def main_menu():
    while True:
        clear_screen()
        files = get_git_status()
        if not files:
            print_header("Git Commit Organizer")
            print(f"{GREEN}No changes detected. Working tree clean!{RESET}")
            break

        groups = group_changes(files)

        print_header("Git Commit Organizer")
        print(f"{BOLD}Status Summary:{RESET}")

        active_categories = []
        for cat_id, info in CATEGORIES.items():
            count = len(groups[cat_id])
            if count > 0:
                print(
                    f"  [{BOLD}{CYAN}{cat_id}{RESET}] {info['name']}: {YELLOW}{count} file(s){RESET}"
                )
                active_categories.append(cat_id)
            else:
                print(
                    f"  [ {WHITE}{cat_id}{RESET} ] {info['name']}: {WHITE}0 file(s){RESET}"
                )

        other_count = len(groups["other"])
        if other_count > 0:
            print(
                f"  [{BOLD}{RED}other{RESET}] Unclassified changes: {YELLOW}{other_count} file(s){RESET}"
            )
            active_categories.append("other")

        print("\n" + f"{BOLD}Options:{RESET}")
        print(f"  [{BOLD}c{RESET}] Auto-Commit a specific category group")
        print(f"  [{BOLD}a{RESET}] Auto-Commit ALL categories sequentially")
        print(f"  [{BOLD}d{RESET}] View diff for a category group")
        print(f"  [{BOLD}t{RESET}] Run validation tests (pytest)")
        print(f"  [{BOLD}s{RESET}] Show raw git status")
        print(f"  [{BOLD}q{RESET}] Exit")

        choice = input("\nSelect an option: ").strip().lower()

        if choice == "q":
            break
        elif choice == "s":
            clear_screen()
            print_header("Raw Git Status")
            subprocess.run(["git", "status"])
            input("\nPress Enter to return to the menu...")
        elif choice == "t":
            run_tests()
            input("\nPress Enter to return to the menu...")
        elif choice == "d":
            if not active_categories:
                print("No modified files to check diff for.")
                continue
            cat = (
                input(f"Enter category ID ({'/'.join(active_categories)}): ")
                .strip()
                .lower()
            )
            if cat in groups and groups[cat]:
                show_diff(cat, groups[cat])
            else:
                print(f"{RED}Invalid or empty category selected.{RESET}")
                input("Press Enter to continue...")
        elif choice == "c":
            if not active_categories:
                print("No modified files to commit.")
                continue
            cat = (
                input(f"Enter category ID ({'/'.join(active_categories)}): ")
                .strip()
                .lower()
            )
            if cat in groups and groups[cat]:
                stage_and_commit(cat, groups[cat])
                input("\nPress Enter to continue...")
            else:
                print(f"{RED}Invalid or empty category selected.{RESET}")
                input("Press Enter to continue...")
        elif choice == "a":
            if not active_categories:
                print("No changes to commit.")
                continue

            print(
                f"\n{BOLD}{YELLOW}Starting batch commit run for categories: {', '.join(active_categories)}{RESET}"
            )
            # Ensure tests pass first
            run_t = (
                input("Do you want to run pytest before starting? [Y/n]: ")
                .strip()
                .lower()
            )
            if run_t != "n":
                if not run_tests():
                    confirm = (
                        input("Tests failed. Do you want to proceed anyway? [y/N]: ")
                        .strip()
                        .lower()
                    )
                    if confirm != "y":
                        continue

            for cat in active_categories:
                if cat in groups and groups[cat]:
                    success = stage_and_commit(cat, groups[cat])
                    if not success:
                        print(
                            f"{RED}Batch commit run aborted/halted at category '{cat}'.{RESET}"
                        )
                        break
            input("\nBatch run finished. Press Enter to return to main menu...")


if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Exiting organizer. Goodbye!{RESET}")
        sys.exit(0)
