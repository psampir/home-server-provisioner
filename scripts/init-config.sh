#!/usr/bin/env bash
#
# Initialise a per-environment config directory under configs/<NAME>/.
#
# Usage:
#   ./scripts/init-config.sh           # creates configs/prod/
#   ./scripts/init-config.sh prod2     # creates configs/prod2/
#
# Copies configs/example/ as the starting tree, initialises a fresh git repo
# inside the new directory (so users can push it to their own private remote
# independently of this provisioner repo), and creates a .gitignore that hides
# the vault password.
#
# Idempotent: refuses to overwrite an existing configs/<NAME>/.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="${1:-prod}"
SRC_DIR="$REPO_ROOT/configs/example"
DEST_DIR="$REPO_ROOT/configs/$NAME"

if [[ ! -d "$SRC_DIR" ]]; then
    echo "Error: $SRC_DIR not found (broken installation?)." >&2
    exit 1
fi

if [[ -e "$DEST_DIR" ]]; then
    echo "configs/$NAME/ already exists - nothing to do."
    echo "(If you want to start over, remove it manually first.)"
    exit 0
fi

echo "Creating configs/$NAME/ from configs/example/ ..."

# Preserve hidden files (e.g. .gitkeep). Use cp -a so timestamps + structure
# carry over verbatim.
cp -a "$SRC_DIR" "$DEST_DIR"

# Rename example files that ship with a .example suffix to their real names.
if [[ -f "$DEST_DIR/inventory/hosts.yml.example" ]]; then
    mv "$DEST_DIR/inventory/hosts.yml.example" "$DEST_DIR/inventory/hosts.yml"
fi

# Initialise a git repo inside the new env so the user can push it to their
# own private remote (independent of the provisioner repo).
cd "$DEST_DIR"
git init --quiet -b main

cat > .gitignore << 'EOF'
# Vault password - must never be committed.
.vault_pass
.vault_password
EOF

git add -A
git commit --quiet -m "Initial $NAME config (from configs/example/)"

cd "$REPO_ROOT"

cat <<EOF

Done. New environment at: configs/$NAME/

Next steps:
  1. Edit configs/$NAME/inventory/hosts.yml and group_vars/all/main.yml
     to match your real hosts and credentials.
  2. Create a vault password:
       make vault-init ENV=$NAME
  3. (Optional) Push to your own private remote:
       cd configs/$NAME && git remote add origin <your-private-repo-url>
       git push -u origin main
  4. Run a first deployment:
       make bootstrap ENV=$NAME
       make provision ENV=$NAME
EOF
