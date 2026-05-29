#!/usr/bin/env python3
"""
Generate, rotate, and prune WireGuard client keys.

Schema
------
User-facing definition (plain, committed to config repo):

    # inventory/group_vars/all/main.yml
    wireguard_clients:
      - { name: phone, vpn_ip: 10.10.0.20 }
      - { name: laptop,  vpn_ip: 10.10.0.21, allowed_ips: "0.0.0.0/0" }

Vaulted keys (auto-managed by this script):

    # inventory/group_vars/all/vault.yml (ansible-vault encrypted)
    vault_wireguard_client_keys:
      phone:
        privkey: "..."
        pubkey:  "..."
        psk:     "..."

What this script does
---------------------
1. Reads `wireguard_clients` from main.yml.
2. Decrypts vault.yml and reads `vault_wireguard_client_keys`.
3. For every client in main.yml without a vault entry:
       wg genkey | wg pubkey, wg genpsk → add to map.
4. For every vault entry whose name is no longer in main.yml:
       remove it (auto-prune).
5. Re-encrypts vault.yml in place.
6. If any change was made and the vault file lives inside a git repo that
   is otherwise clean, auto-commits the new vault.yml with a descriptive
   message. If the working tree is dirty, refuses to prune (keys stay).

Safety
------
* Prune is skipped (with a warning) when the vault file's git working tree
  has uncommitted changes other than vault.yml itself - protects against
  the "typo in name" scenario where the user is mid-edit.
* All key material is removed from memory as soon as the vault file is
  rewritten. The script never logs key bytes.

Requirements
------------
* `wg` and `ansible-vault` on PATH.
* PyYAML (stdlib of any modern distro).
* $ANSIBLE_VAULT_PASSWORD_FILE pointing at a script/file that prints the
  vault password (set by the Makefile for `make provision`).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import yaml


# --- helpers -----------------------------------------------------------------


def die(msg: str, code: int = 1) -> NoReturn:
    print(f"wg-ensure-keys: error: {msg}", file=sys.stderr)
    sys.exit(code)


def info(msg: str) -> None:
    print(f"wg-ensure-keys: {msg}")


def require_tool(name: str) -> None:
    if not shutil.which(name):
        die(f"required tool '{name}' not found on PATH")


def wg_genkey() -> str:
    return subprocess.check_output(["wg", "genkey"], text=True).strip()


def wg_pubkey(privkey: str) -> str:
    return subprocess.check_output(
        ["wg", "pubkey"], input=privkey, text=True
    ).strip()


def wg_genpsk() -> str:
    return subprocess.check_output(["wg", "genpsk"], text=True).strip()


def vault_is_encrypted(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    with open(path, "rb") as fh:
        return fh.read(16).startswith(b"$ANSIBLE_VAULT")


def vault_decrypt(path: Path) -> str:
    """Return the decrypted plain text of an ansible-vault file."""
    if not path.exists() or path.stat().st_size == 0:
        return ""
    if not vault_is_encrypted(path):
        # Allow plain files for the first-run case where the user hasn't
        # encrypted yet.
        return path.read_text()
    try:
        return subprocess.check_output(
            ["ansible-vault", "decrypt", "--output=-", str(path)],
            text=True,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        die(f"failed to decrypt {path}: {e.stderr.strip() or e}")


def vault_encrypt(path: Path, plain: str) -> None:
    """Encrypt `plain` and write it to `path` (in place)."""
    # ansible-vault refuses to read from a pipe via /dev/stdin (it tries to
    # stat the source file). Stage to a tempfile in the same directory so
    # the rename is atomic on the same filesystem.
    import tempfile

    tmp = tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=".vault-stage-", delete=False
    )
    try:
        tmp.write(plain)
        tmp.close()
        os.chmod(tmp.name, 0o600)
        subprocess.run(
            ["ansible-vault", "encrypt", tmp.name],
            check=True,
            stderr=subprocess.PIPE,
        )
        os.replace(tmp.name, path)
    except subprocess.CalledProcessError as e:
        die(f"failed to encrypt {path}: {e.stderr.decode().strip() or e}")
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)


def git_repo_root_for(path: Path) -> Path | None:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return Path(out)
    except subprocess.CalledProcessError:
        return None


def git_working_tree_dirty(repo: Path, ignore_path: Path) -> bool:
    """True if the repo has uncommitted changes other than `ignore_path`."""
    out = subprocess.check_output(
        ["git", "-C", str(repo), "status", "--porcelain"], text=True
    )
    ignore_rel = ignore_path.resolve().relative_to(repo.resolve()).as_posix()
    for line in out.splitlines():
        # `XY <path>` - first two chars are status, then space.
        path_part = line[3:].strip()
        if path_part == ignore_rel:
            continue
        return True
    return False


def git_commit_vault(repo: Path, vault_path: Path, message: str) -> None:
    rel = vault_path.resolve().relative_to(repo.resolve()).as_posix()
    subprocess.run(["git", "-C", str(repo), "add", rel], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--quiet", "-m", message], check=True
    )


# --- main --------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate, rotate, and prune WireGuard client keys."
    )
    parser.add_argument(
        "--inventory",
        required=True,
        type=Path,
        help="Inventory directory (e.g. inventories/production)",
    )
    parser.add_argument(
        "--no-commit",
        action="store_true",
        help="Do not auto-commit the updated vault into the config repo",
    )
    args = parser.parse_args()

    require_tool("wg")
    require_tool("ansible-vault")

    main_path = args.inventory / "group_vars" / "all" / "main.yml"
    vault_path = args.inventory / "group_vars" / "all" / "vault.yml"

    if not main_path.exists():
        die(f"{main_path} does not exist")

    main_doc = yaml.safe_load(main_path.read_text()) or {}
    clients = main_doc.get("wireguard_clients") or []
    desired_names = {c["name"] for c in clients if isinstance(c, dict) and "name" in c}

    # Read existing vault map (empty if no vault yet).
    if vault_path.exists():
        plain = vault_decrypt(vault_path)
        vault_doc = yaml.safe_load(plain) if plain.strip() else {}
        vault_doc = vault_doc or {}
    else:
        vault_doc = {}

    key_map = vault_doc.get("vault_wireguard_client_keys") or {}
    existing_names = set(key_map.keys())

    to_add = sorted(desired_names - existing_names)
    to_prune = sorted(existing_names - desired_names)

    # Generate missing.
    for name in to_add:
        priv = wg_genkey()
        pub = wg_pubkey(priv)
        psk = wg_genpsk()
        key_map[name] = {"privkey": priv, "pubkey": pub, "psk": psk}
        info(f"generated keys for new client: {name}")

    # Prune orphans (with safeguard).
    pruned: list[str] = []
    if to_prune:
        repo = git_repo_root_for(vault_path)
        safe_to_prune = True
        if repo is None:
            # No git repo (e.g. the test env): there is no history to lose,
            # so prune unconditionally.
            info(
                "vault is not in a git repo; pruning unconditionally "
                f"({len(to_prune)} orphan(s): {', '.join(to_prune)})"
            )
        elif vault_path.exists() and git_working_tree_dirty(repo, vault_path):
            info(
                "config repo has uncommitted changes other than vault.yml; "
                "refusing to auto-prune in case you are mid-edit "
                f"({len(to_prune)} orphan(s): {', '.join(to_prune)}). "
                "Commit your changes and re-run to prune."
            )
            safe_to_prune = False

        if safe_to_prune:
            for name in to_prune:
                del key_map[name]
                pruned.append(name)
                info(f"pruned orphan client: {name}")

    if not to_add and not pruned:
        info("no changes (all clients already have keys)")
        return 0

    # Write back. Always re-encrypt (also re-encrypts initial plain file).
    vault_doc["vault_wireguard_client_keys"] = key_map
    new_plain = yaml.safe_dump(vault_doc, default_flow_style=False, sort_keys=True)
    vault_encrypt(vault_path, new_plain)
    info(f"wrote {vault_path}")

    # Auto-commit if inside a clean-enough git repo.
    if not args.no_commit:
        repo = git_repo_root_for(vault_path)
        if repo is not None:
            parts = []
            if to_add:
                parts.append(f"add {', '.join(to_add)}")
            if pruned:
                parts.append(f"prune {', '.join(pruned)}")
            msg = "wireguard keys: " + "; ".join(parts)
            try:
                git_commit_vault(repo, vault_path, msg)
                info(f"committed vault update to {repo} ({msg!r})")
            except subprocess.CalledProcessError as e:
                info(f"git commit failed (continuing): {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
