# compose_deploy

Deploys Docker Compose stacks from the controller to `/opt/stacks/<stack>/`
and runs `docker compose up -d`.

## What it does

- discovers stacks under `configs/<ENV>/stacks/_common/<name>/` and
  `configs/<ENV>/stacks/<hostname>/<name>/`
- copies each stack directory verbatim, including `.env`, Caddyfiles and
  `config/` directories
- creates any external Docker networks listed in
  `compose_deploy_external_networks` before deploying
- brings each stack up with `docker compose up -d`
- removes stacks whose `state` is `absent`

Host-specific directories win over `_common` per stack name (full directory
override, no file-level merge).

## Variables

| Variable | Default | Description |
|---|---|---|
| `compose_deploy_base_dir` | `/opt/stacks` | Destination root on the host |
| `compose_deploy_src_root` | `{{ inventory_dir }}/../stacks` | Source root on the controller |
| `compose_deploy_common_subdir` | `_common` | Stacks deployed to every host |
| `compose_deploy_host_subdir` | `{{ inventory_hostname }}` | Host-specific stacks |
| `compose_deploy_owner` | `admin_user_name` | Owner of the stack directories |
| `compose_deploy_group` | `admin_user_name` | Group of the stack directories |
| `compose_deploy_external_networks` | `[]` | Networks created before deployment, e.g. `[reverse_proxy]` |
| `compose_deploy_stacks` | `[]` | Explicit stack list, overrides discovery |
| `compose_deploy_parallel_limit` | `1` | `COMPOSE_PARALLEL_LIMIT` for pull/build concurrency |
| `compose_deploy_file_mode` | `preserve` | Mode for synced stack files (`preserve` or octal) |
| `compose_deploy_directory_mode` | `preserve` | Mode for created subdirectories (`preserve` or octal) |

## File modes and build contexts

Stack files are synced with `compose_deploy_file_mode`, which defaults to
`preserve`: the mode of the file in `configs/<ENV>/stacks/` is kept. This
matters when a stack builds an image from its own directory. Docker's `COPY`
preserves file modes, so a build-context file synced as `0640 root:root`
stays unreadable for a non-root user in the image, and the build or the
container fails with a permission error.

Keep build-context files world-readable (`0644` for files, `0755` for
directories) in the config repository, or add an explicit `chmod` in the
`Dockerfile` when the source mode cannot change. Do not "fix" this by
loosening every stack file: configuration and secrets should stay private.

Directories created by the recursive copy follow
`compose_deploy_directory_mode`. Ansible has no `preserve` for directories,
so the default `preserve` means directory modes are not managed (new
directories get the system default). Set an octal mode to enforce one.

The rendered `.env` file is always written `0640` and is not affected by
`compose_deploy_file_mode`. It usually contains credentials, and Compose
reads it as the deployment user, not as a user inside a build container.
Never place secrets in a file that must be readable by a non-root build
user; pass them at runtime instead.

## Pull concurrency

`compose_deploy_parallel_limit` (default `1`) is exported as
`COMPOSE_PARALLEL_LIMIT` for every `docker compose` call. Compose defaults
to 5 concurrent pulls/builds, which can hit registry rate limits when a
fresh host deploys many stacks in one run. Raise it when the registry
credentials and network link allow it.

## External networks

A stack that declares a shared network must not try to create it on every
host. Declare the network once per host:

```yaml
compose_deploy_external_networks:
  - reverse_proxy
```

and keep `external: true` in the stack compose files.

## Explicit stack list

For per-host templated `.env` files or to rename a source tree, set
`compose_deploy_stacks`:

```yaml
compose_deploy_stacks:
  - name: whoami
    env:
      WHOAMI_PORT: "8080"
```

Each entry supports `name`, `state` (`present`/`absent`), `pull`
(`always`/`missing`/`never`), `src_dir` and `env`.
