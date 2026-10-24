#!/usr/bin/env python3
"""Static contract checks for the new Makefile targets."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def dry_run(*args: str) -> str:
    result = subprocess.run(
        ["make", "-n", *args],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result.stdout


def main() -> int:
    stacks = dry_run("stacks", "ENV=test", "LIMIT=test")
    if "playbooks/stacks.yml" not in stacks:
        raise SystemExit("stacks target does not use playbooks/stacks.yml")
    if "playbooks/site.yml" in stacks:
        raise SystemExit("stacks target unexpectedly uses the full site playbook")
    if "--limit test" not in stacks:
        raise SystemExit("stacks target does not forward LIMIT")

    rekey = dry_run("vault-rekey", "ENV=test")
    if "--new-vault-password-file" not in rekey:
        raise SystemExit("vault-rekey does not pass a new password file")
    if "env -u ANSIBLE_VAULT_PASSWORD_FILE" not in rekey:
        raise SystemExit("vault-rekey does not clear the exported password file")

    print("makefile contract tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
