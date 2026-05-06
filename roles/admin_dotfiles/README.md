# admin_dotfiles

Mirrors a directory of dotfiles from the control machine (typically
`config/dotfiles/home/`, created by `scripts/init-config.sh`) into the
admin user's home directory on every server.

Shell-agnostic: the role copies files verbatim and has no knowledge of
fish, bash, zoxide or any specific tool.

## Source layout

`admin_dotfiles_src` mirrors the admin user's home directory. Example:

```
config/dotfiles/home/
├── .gitconfig
├── .tmux.conf
└── .config/
    ├── fish/
    │   └── config.fish
    └── git/
        └── config
```

After provisioning, those exact paths exist under the admin user's
home directory.

## Sync semantics - strict, but only for managed files

The role tracks which files it owns via a per-host manifest stored at
`~admin/.config/admin_dotfiles.manifest`. On every run:

1. The control-machine source tree is walked recursively to build the
   current set of managed files (paths relative to `admin_dotfiles_src`).
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

- Per-host: set `admin_dotfiles_src: ""` in `host_vars/<host>.yml`.
- Globally: same in `group_vars/all.yml`.
- Implicitly: if the source directory does not exist on the control
  machine, the role logs a notice and does nothing.

## Variables

| Variable | Default | Description |
|---|---|---|
| `admin_dotfiles_src` | `{{ playbook_dir }}/../config/dotfiles/home` | Source directory on the control machine. |
| `admin_dotfiles_manifest` | `.config/admin_dotfiles.manifest` | Path (relative to admin user's home) of the per-host manifest. |
