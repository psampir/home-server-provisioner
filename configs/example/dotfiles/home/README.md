# Dotfiles

Files placed under `home/` are copied into the admin user's home directory by
the `admin_dotfiles` role.

The directory tree mirrors `$HOME` exactly. For example:

    home/.config/fish/config.fish   ->   ~/.config/fish/config.fish
    home/.bashrc                    ->   ~/.bashrc

Hidden files and directories are preserved. Existing files on the target are
overwritten only if their content differs.

See `roles/admin_dotfiles/` in the provisioner repo for the full sync logic.
