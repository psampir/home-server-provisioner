# Managed by home-server-provisioner via admin_dotfiles
set -g fish_greeting

if status is-interactive
    if type -q zoxide
        zoxide init fish --cmd cd | source
    end
end
