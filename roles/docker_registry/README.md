# docker_registry

Logs the Docker CLI in to private container registries before
`compose_deploy` pulls images. The role is inert when `docker_registry_logins`
is empty.

## Variables

| Variable | Default | Description |
|---|---|---|
| `docker_registry_logins` | `[]` | List of `registry`, `username`, `password` entries |

```yaml
docker_registry_logins:
  - registry: ghcr.io
    username: psampir
    password: "{{ vault_ghcr_token }}"
```

## Notes

- The login is written for the user running the Docker CLI. Run the role as
  the same remote user that runs `compose_deploy`; do not `become` to root
  unless the compose role also runs as root.
- Keep the token in Ansible Vault. A fine-grained GitHub token needs
  `Packages: read`; a classic token needs `read:packages`.
- `reauthorize: true` refreshes an expired login on every run. Rotate the
  token by changing the vault value and re-running the role.
- The rendered Docker config is readable by that user, which is the same
  trust boundary as the Docker socket.
