# admin_dotfiles

Mirrors one or two dotfile trees from the control machine into the admin
user's home directory on every server. The layout is created by
`scripts/init-config.sh` under `configs/<ENV>/dotfiles/`.

Shell-agnostic: the role copies files verbatim and has no knowledge of
fish, bash, zoxide or any specific tool.

## Source layout

There are two overlays under `admin_dotfiles_root`:

```
configs/<ENV>/dotfiles/
├── _common/home/                → baseline, applied to every host
│   ├── .gitconfig
│   └── .config/fish/config.fish
└── <inventory_hostname>/home/   → per-host overlay (optional)
    └── .config/git/config
```

Both directories mirror the admin user's home directory exactly. They are
applied **in order** - `_common` first, then the host directory - and the
host overlay wins **per file**, not per directory. That means a host can
override `.config/fish/config.fish` while the rest of the baseline still
ships, and can add files that do not exist in `_common` at all.

After provisioning, those exact paths exist under the admin user's home
directory. The two subdirectory names are configurable via
`admin_dotfiles_common_subdir` and `admin_dotfiles_host_subdir`.

## Sync semantics - strict, but only for managed files

The role tracks which files it owns via a per-host manifest stored at
`~admin/.config/admin_dotfiles.manifest`. On every run:

1. The control-machine source tree is walked recursively to build the
   current set of managed files (paths relative to each overlay).
2. Each managed file is copied to the corresponding path under the
   admin user's home directory.
3. The previous manifest is compared with the current one; any path
   that was managed before and is no longer in the source is removed.
4. The new manifest is written back.

This gives "single source of truth" semantics for managed paths only.
Crucially, **files in directories you do not ship are never touched**.
For example, you can ship `.config/fish/config.fish` as a single file
without losing `~admin/.config/fish/conf.d/`, `fish_variables`, or
`~admin/.local/share/fish/fish_history`.

The same applies to runtime state at the home root: `.bash_history`,
`.lesshst`, `.viminfo`, `.cache/`, `.local/`, `.gnupg/`, etc. all
remain untouched unless you explicitly add them to the source repo
(don't).

## Granularity rule of thumb

Ship the smallest paths that cover what you want to manage:

- `~/.gitconfig` → put `.gitconfig` in the source. ✅
- `fish prompt + abbreviations` → put `.config/fish/config.fish` and/or
  individual `.config/fish/conf.d/<name>.fish` files. ✅
- A whole nvim config tree → put `.config/nvim/` with all its files.
  All files inside it then become managed; anything previously synced
  there but no longer in the source will be removed on the next run. ✅

## File modes

File modes are preserved from the source repo. If you check in a script
under `.local/bin/` with `chmod +x`, it will land on the server
executable. (Git tracks the executable bit, so this works through the
private config repo.)

## Disabling

- Per-host: set `admin_dotfiles_root: ""` in `host_vars/<host>.yml`.
- Globally: same in `group_vars/all/main.yml`.
- Implicitly: if the source directory does not exist on the control
  machine, the role logs a notice and does nothing.

## Variables

| Variable | Default | Description |
|---|---|---|
| `admin_dotfiles_root` | `{{ inventory_dir }}/../dotfiles` | Root of the overlay tree on the control machine. Empty disables the role. |
| `admin_dotfiles_common_subdir` | `_common/home` | Baseline overlay, relative to `admin_dotfiles_root`. |
| `admin_dotfiles_host_subdir` | `{{ inventory_hostname }}/home` | Host overlay, applied after (and winning over) the baseline. |
| `admin_dotfiles_manifest` | `.config/admin_dotfiles.manifest` | Path (relative to admin user's home) of the per-host manifest. |
