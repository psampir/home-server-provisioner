# Dotfiles

Files placed under the overlay directories are copied into the admin user's
home directory by the `admin_dotfiles` role.

## Layout (overlay, file-level)

    dotfiles/
    ├── _common/home/              ← baseline, deployed to every host
    │   └── .config/fish/config.fish
    └── <inventory_hostname>/home/  ← optional per-host overlay
        └── .config/fish/conf.d/host-specific.fish

For each managed file, the per-host overlay wins. So you can ship a single
common `config.fish` and add a host-only `conf.d/foo.fish` without
re-stating the rest of the tree.

The directory tree under `home/` mirrors `$HOME` exactly:

    _common/home/.config/fish/config.fish   ->   ~/.config/fish/config.fish
    _common/home/.bashrc                    ->   ~/.bashrc

Hidden files and directories are preserved. Existing files on the target are
overwritten only if their content differs. Files removed from both overlays
are deleted on the next run (tracked via a per-host manifest).

See `roles/admin_dotfiles/` in the provisioner repo for the full sync logic.
