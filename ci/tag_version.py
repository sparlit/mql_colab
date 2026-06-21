"""Semantic version tagging script for CI.

This script is intended to run after a successful merge to the `main` branch.
It determines the latest git tag that follows the pattern ``vMAJOR.MINOR.PATCH``
(including a leading ``v``), increments the PATCH number, creates a new tag,
and pushes it back to the remote repository.

The script uses ``subprocess`` to invoke git commands and assumes that the CI
environment has the appropriate write permissions for the repository.
"""

import subprocess
import re
import sys
from pathlib import Path

def run_git(args):
    """Run a git command and return its stdout stripped."""
    result = subprocess.run(["git"] + args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Git command failed: git {' '.join(args)}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()

def get_latest_tag():
    """Return the most recent tag matching ``vX.Y.Z`` or ``None`` if none exist."""
    tags = run_git(["tag", "--list", "v*.*.*"]).splitlines()
    if not tags:
        return None
    # Sort tags using semantic version ordering
    def key(tag):
        parts = tag.lstrip("v").split('.')
        return tuple(int(p) for p in parts)
    return sorted(tags, key=key)[-1]

def bump_version(tag):
    """Increment the PATCH component of a ``vX.Y.Z`` tag."""
    major, minor, patch = (int(p) for p in tag.lstrip('v').split('.'))
    return f"v{major}.{minor}.{patch+1}"

def main():
    # Ensure we are on the main branch
    current_branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if current_branch != "main":
        print(f"Not on main branch (currently on {current_branch}); skipping tag.")
        sys.exit(0)

    latest = get_latest_tag()
    if latest:
        new_tag = bump_version(latest)
    else:
        # No existing tags – start with v0.1.0
        new_tag = "v0.1.0"
    print(f"Creating new tag: {new_tag}")
    run_git(["tag", new_tag])
    run_git(["push", "origin", new_tag])

if __name__ == "__main__":
    main()
