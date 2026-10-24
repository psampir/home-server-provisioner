#!/usr/bin/env python3
"""Exercise the interactive vault-rekey target on a temporary environment."""

from __future__ import annotations

import os
import pty
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENV = "test-rekey"
ENV_DIR = REPO / "configs" / ENV
VAULT = ENV_DIR / "inventory/group_vars/all/vault.yml"
PASS_FILE = ENV_DIR / ".vault_pass"
OLD_PASSWORD = "old-test-password"
NEW_PASSWORD = "new-test-password"
TIMEOUT = 30


def read_until(master: int, output: bytearray, marker: bytes) -> None:
    deadline = time.time() + TIMEOUT
    while output.find(marker) < 0:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(f"timed out waiting for {marker!r}")
        ready, _, _ = select.select([master], [], [], remaining)
        if not ready:
            raise TimeoutError(f"timed out waiting for {marker!r}")
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        output.extend(chunk)
    if output.find(marker) < 0:
        raise RuntimeError(f"process ended before {marker!r}")


def view_vault(password_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "ansible-vault",
            "view",
            "--vault-password-file",
            str(password_file),
            str(VAULT),
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )


def main() -> int:
    if ENV_DIR.exists():
        shutil.rmtree(ENV_DIR)
    try:
        (ENV_DIR / "inventory/group_vars/all").mkdir(parents=True)
        plain = ENV_DIR / "plain.yml"
        plain.write_text("test: value\n", encoding="utf-8")
        PASS_FILE.write_text(OLD_PASSWORD, encoding="utf-8")
        os.chmod(PASS_FILE, 0o600)
        old_password_file = ENV_DIR / "old-password"
        old_password_file.write_text(OLD_PASSWORD, encoding="utf-8")
        os.chmod(old_password_file, 0o600)

        subprocess.run(
            [
                "ansible-vault",
                "encrypt",
                "--vault-password-file",
                str(PASS_FILE),
                "--output",
                str(VAULT),
                str(plain),
            ],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        )

        master, slave = pty.openpty()
        process = subprocess.Popen(
            ["make", "vault-rekey", f"ENV={ENV}"],
            cwd=REPO,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
        )
        os.close(slave)
        output = bytearray()
        try:
            read_until(master, output, b"New vault password")
            os.write(master, (NEW_PASSWORD + "\n").encode())
            read_until(master, output, b"Confirm new vault password")
            os.write(master, (NEW_PASSWORD + "\n").encode())
            while True:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
            returncode = process.wait(timeout=TIMEOUT)
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
                process.wait()

        if returncode != 0:
            sys.stdout.buffer.write(output)
            raise SystemExit(f"vault-rekey failed with {returncode}")

        if PASS_FILE.read_text(encoding="utf-8") != NEW_PASSWORD:
            raise SystemExit(".vault_pass was not updated")
        if (PASS_FILE.stat().st_mode & 0o777) != 0o600:
            raise SystemExit(".vault_pass mode is not 0600")

        new_view = view_vault(PASS_FILE)
        old_view = view_vault(old_password_file)
        if new_view.returncode != 0 or new_view.stdout.strip() != "test: value":
            raise SystemExit("new password does not decrypt the vault")
        if old_view.returncode == 0:
            raise SystemExit("old password still decrypts the vault")

        print("vault-rekey test passed")
        return 0
    finally:
        if ENV_DIR.exists():
            shutil.rmtree(ENV_DIR)


if __name__ == "__main__":
    raise SystemExit(main())
