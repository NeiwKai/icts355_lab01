"""Lab 4 — Secret Scanner Script.

Scans git history and tracked files for accidental leaks of high-risk credentials
(e.g., GCP/AWS keys, private keys, API tokens).

Requires full git history (fetch-depth: 0). Refuses to run on shallow checkouts.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# High-risk credential regex patterns
SECRET_PATTERNS = [
    (
        "GCP Service Account / Private Key",
        re.compile(r"\"private_key\":\s*\"-----BEGIN PRIVATE KEY-----"),
    ),
    (
        "AWS Access Key ID",
        re.compile(r"(?<![A-Z0-9])[A-Z0-9]{20}(?![A-Z0-9])"),
    ),
    (
        "AWS Secret Access Key",
        re.compile(r"(?<![A-Za-z0-9/+=])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])"),
    ),
    (
        "RSA / Generic Private Key",
        re.compile(r"-----BEGIN (RSA|OPENSSH|EC|PGP) PRIVATE KEY-----"),
    ),
    (
        "GitHub Personal Access Token",
        re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    ),
    (
        "Generic Secret Assignment",
        re.compile(
            r"(?i)(api[_-]?key|secret[_-]?key|password|auth[_-]?token)\s*=\s*['\"][A-Za-z0-9%_.-]{16,}['\"]"
        ),
    ),
]

# File extensions that contain binary blobs or non-text hashes
EXCLUDED_EXTENSIONS = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".joblib",
    ".pkl",
    ".pyc",
    ".zip",
    ".gz",
    ".tar",
}


def check_git_depth() -> None:
    """Refuse to run if repo is a shallow clone (fetch-depth != 0)."""
    try:
        is_shallow = (
            subprocess.check_output(
                ["git", "rev-parse", "--is-shallow-repository"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            .strip()
            .lower()
        )
        if is_shallow == "true":
            print(
                "❌ ERROR: Shallow git checkout detected (fetch-depth: 1)."
            )
            print(
                "scripts/scan_secrets.py requires a full checkout (fetch-depth: 0) to scan commit history."
            )
            sys.exit(1)
    except subprocess.CalledProcessError:
        pass  # Not a git repository, proceed with local file scanning


def scan_git_history() -> bool:
    """Scan all commits in git history for secret patterns."""
    print("🔍 Scanning full git commit history...")
    found_secrets = False

    try:
        git_log = subprocess.check_output(
            ["git", "log", "-p", "--all"], text=True, errors="ignore"
        )
    except subprocess.CalledProcessError as err:
        print(f"⚠️ Failed to retrieve git log: {err}")
        return False

    for name, pattern in SECRET_PATTERNS:
        for line in git_log.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                # Avoid matching the scanner script itself or dummy/example lines
                if "scan_secrets.py" in line or "dummy" in line.lower():
                    continue
                if pattern.search(line):
                    print(f"❌ SECRET LEAK DETECTED in git history: [{name}]")
                    print(f"   Line: {line.strip()[:80]}...")
                    found_secrets = True
                    break

    return found_secrets


def scan_tracked_files() -> bool:
    """Scan workspace files for uncommitted secrets."""
    print("🔍 Scanning workspace files...")
    found_secrets = False
    repo_root = Path(__file__).resolve().parent.parent

    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue

        # Skip git metadata, virtual environments, cache directories, and local MLflow tracking outputs
        if any(
            p in path.parts
            for p in [
                ".git",
                ".venv",
                "venv",
                "__pycache__",
                ".pytest_cache",
                ".mypy_cache",
                ".ruff_cache",
                "mlruns",
                "mlartifacts",
                ".dvc",
            ]
        ):
            continue

        # Skip scanner script itself and binary/database files
        if path.name == "scan_secrets.py" or path.suffix in EXCLUDED_EXTENSIONS:
            continue

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            for name, pattern in SECRET_PATTERNS:
                if pattern.search(content):
                    print(
                        f"❌ SECRET DETECTED in file: {path.relative_to(repo_root)} [{name}]"
                    )
                    found_secrets = True
        except Exception:
            continue

    return found_secrets


def main() -> None:
    check_git_depth()
    secrets_in_history = scan_git_history()
    secrets_in_files = scan_tracked_files()

    if secrets_in_history or secrets_in_files:
        print("\n💥 Secret scan FAILED! Clean or revoke disclosed keys before committing.")
        sys.exit(1)

    print("\n✅ Secret scan PASSED! No credentials or keys detected.")
    sys.exit(0)


if __name__ == "__main__":
    main()
