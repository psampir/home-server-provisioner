#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_DIR="$REPO_ROOT/config"

if [ -d "$CONFIG_DIR/.git" ]; then
    echo "Config repo already initialised at config/"
    exit 0
fi

echo "Initialising config directory..."

# Create directory structure
mkdir -p "$CONFIG_DIR/inventory/group_vars"
mkdir -p "$CONFIG_DIR/inventory/host_vars"
mkdir -p "$CONFIG_DIR/dotfiles/home"

# Seed dotfiles/ with a README so the directory is tracked and self-documenting
if [ ! -f "$CONFIG_DIR/dotfiles/README.md" ]; then
    cat > "$CONFIG_DIR/dotfiles/README.md" << 'EOF'
# dotfiles/

Files placed under `dotfiles/home/` are mirrored into the admin user's
home directory by the `admin_dotfiles` role.

Layout mirrors the target home directly. For example:

    dotfiles/home/.config/fish/config.fish
        → ~admin/.config/fish/config.fish
    dotfiles/home/.gitconfig
        → ~admin/.gitconfig

Only files actually present here are managed. Removing a file from
`dotfiles/home/` causes it to be removed from the server on the next
run (tracked via a per-host manifest at
`~admin/.config/admin_dotfiles.manifest`).

Runtime state in unshipped paths (`.bash_history`, `fish_history`,
`.cache/`, etc.) is never touched.
EOF
    echo "  seeded: $CONFIG_DIR/dotfiles/README.md"
fi

# Copy example files as starting points (don't overwrite existing)
copy_example() {
    local src="$1" dest="$2"
    if [ -f "$dest" ]; then
        echo "  exists: $dest (skipping)"
    elif [ -f "$src" ]; then
        cp "$src" "$dest"
        echo "  copied: $dest"
    fi
}

copy_example "$REPO_ROOT/.env.example" "$CONFIG_DIR/.env"
copy_example "$REPO_ROOT/inventories/production/hosts.yml.example" "$CONFIG_DIR/inventory/hosts.yml"
copy_example "$REPO_ROOT/inventories/production/group_vars/all.yml.example" "$CONFIG_DIR/inventory/group_vars/all.yml"

# Move existing user config files into config/ if they exist (and aren't symlinks)
move_if_exists() {
    local src="$1" dest="$2"
    if [ -f "$src" ] && [ ! -L "$src" ]; then
        mv "$src" "$dest"
        echo "  moved: $src → $dest"
    fi
}

move_if_exists "$REPO_ROOT/.env" "$CONFIG_DIR/.env"
move_if_exists "$REPO_ROOT/inventories/production/hosts.yml" "$CONFIG_DIR/inventory/hosts.yml"
move_if_exists "$REPO_ROOT/inventories/production/group_vars/all.yml" "$CONFIG_DIR/inventory/group_vars/all.yml"

# Create symlinks (relative paths for portability)
create_link() {
    local target="$1" link="$2"
    if [ -L "$link" ]; then
        echo "  linked: $link (already)"
        return
    fi
    ln -sf "$target" "$link"
    echo "  linked: $link"
}

create_link "config/.env" "$REPO_ROOT/.env"
create_link "../../config/inventory/hosts.yml" "$REPO_ROOT/inventories/production/hosts.yml"
create_link "../../../config/inventory/group_vars/all.yml" "$REPO_ROOT/inventories/production/group_vars/all.yml"
create_link "../../../config/inventory/host_vars" "$REPO_ROOT/inventories/production/host_vars"

# Initialise git repo inside config/
cd "$CONFIG_DIR"
git init --quiet -b main

cat > .gitignore << 'EOF'
.vault_pass
.vault_password
EOF

git add -A
git commit --quiet -m "Initial config"

echo ""
echo "Config repo created at config/"
echo ""
echo "Next steps:"
echo "  1. Edit config files to match your environment"
echo "  2. Add a private remote:"
echo "     cd config && git remote add origin <your-private-repo-url>"
echo "  3. Push: cd config && git push -u origin main"
