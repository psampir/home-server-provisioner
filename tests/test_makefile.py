#!/usr/bin/env python3
"""Static contract checks for the new Makefile targets."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

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

    stacks_tagged = dry_run("stacks", "ENV=test", "LIMIT=test", "TAGS=compose_deploy")
    if "--tags 'compose_deploy'" not in stacks_tagged:
        raise SystemExit("stacks target does not forward TAGS")

    provision = dry_run("provision", "ENV=test", "LIMIT=test")
    if "playbooks/site.yml" not in provision:
        raise SystemExit("provision target does not use playbooks/site.yml")
    if "--limit test" not in provision:
        raise SystemExit("provision target does not forward LIMIT")
    if "wg-ensure-keys.py" not in provision:
        raise SystemExit("provision target no longer runs wireguard-keys by default")

    tagged = dry_run("provision", "ENV=test", "LIMIT=test", "TAGS=gatus")
    if "--tags 'gatus'" not in tagged:
        raise SystemExit("provision target does not forward TAGS")
    if "--limit test" not in tagged:
        raise SystemExit("tagged provision drops LIMIT")
    if "wg-ensure-keys.py" in tagged:
        raise SystemExit("tagged provision still runs wireguard-keys")

    plan = dry_run("plan", "ENV=test", "LIMIT=test", "TAGS=gatus")
    if "--tags 'gatus'" not in plan:
        raise SystemExit("plan target does not forward TAGS")
    if "--list-tasks" not in plan:
        raise SystemExit("plan target no longer lists tasks")

    for name in ("playbooks/site.yml", "playbooks/stacks.yml"):
        plays = yaml.safe_load((REPO / name).read_text())
        for play in plays:
            for role in play.get("roles", []):
                if not isinstance(role, dict):
                    raise SystemExit(f"{name}: role {role!r} has no tags")
                tags = role.get("tags") or []
                if role.get("role") not in tags:
                    raise SystemExit(
                        f"{name}: role {role.get('role')} lacks its own name as a tag"
                    )

    site = yaml.safe_load((REPO / "playbooks/site.yml").read_text())
    compose = [
        role
        for play in site
        for role in play.get("roles", [])
        if role.get("role") == "compose_deploy"
    ]
    if not compose or "stacks" not in compose[0].get("tags", []):
        raise SystemExit("compose_deploy is missing the 'stacks' tag in site.yml")

    rekey = dry_run("vault-rekey", "ENV=test")
    if "--new-vault-password-file" not in rekey:
        raise SystemExit("vault-rekey does not pass a new password file")
    if "env -u ANSIBLE_VAULT_PASSWORD_FILE" not in rekey:
        raise SystemExit("vault-rekey does not clear the exported password file")

    print("makefile contract tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
