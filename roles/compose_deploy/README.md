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
