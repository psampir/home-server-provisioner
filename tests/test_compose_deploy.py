#!/usr/bin/env python3
"""Local integration test for compose_deploy .env.j2 and config rendering."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLAYBOOK = REPO / "tests/compose_deploy.yml"
TEST_SECRET = "test-secret-value"
VAULT_PASSWORD = "test-vault-password"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hsp-compose-") as tmp:
        root = Path(tmp)
        plain_vault = root / "vault-plain.yml"
        vault_file = root / "vault.yml"
        vault_pass = root / "vault-pass"
        plain_vault.write_text(f"test_secret: {TEST_SECRET}\n", encoding="utf-8")
        vault_pass.write_text(VAULT_PASSWORD, encoding="utf-8")
        os.chmod(vault_pass, 0o600)

        subprocess.run(
            [
                "ansible-vault",
                "encrypt",
                "--vault-password-file",
                str(vault_pass),
                "--output",
                str(vault_file),
                str(plain_vault),
            ],
            check=True,
            cwd=REPO,
            capture_output=True,
            text=True,
        )

        command = [
            "ansible-playbook",
            str(PLAYBOOK),
            "-i",
            "localhost,",
            "-c",
            "local",
            "--vault-password-file",
            str(vault_pass),
            "-e",
            f"test_vault_file={vault_file}",
            "-e",
            f"test_root={root}",
        ]
        result = subprocess.run(
            command,
            check=False,
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
            return result.returncode

    print("compose_deploy local tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
