# compose_deploy

Deploys Docker Compose stacks from the controller to `/opt/stacks/<stack>/`
and runs `docker compose up -d`.

## What it does

- discovers stacks under `configs/<ENV>/stacks/_common/<name>/` and
  `configs/<ENV>/stacks/<hostname>/<name>/`
- copies each stack directory, including `.env`, Caddyfiles and `config/`
  directories
- renders deployment `*.j2` files from the stack source on the controller and
  writes them next to the stack without the `.j2` suffix (the secret-file path)
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
| `compose_deploy_template_mode` | `0640` | Mode for files rendered from `*.j2` templates |

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

## Secret files and `.j2` templates

Keep secrets out of the stack source. Put them in the Ansible vault and
reference the `vault_*` variables from a `.j2` file in the stack directory:

```text
configs/<ENV>/stacks/<host>/<stack>/.env.j2
```

```jinja
DB_PASSWORD={{ vault_example_db_password }}
PUBLIC_URL=https://example.invalid
```

The role renders deployment templates on the controller with the target
host's variables (including vault variables) and writes the result to the
same relative path without the suffix. `.env.j2` becomes `.env`,
`config/users.j2` becomes `config/users`, and so on. Rendered files use
`compose_deploy_template_mode` (default `0640`); the `.j2` source itself
contains only variable references and can be committed.

Only these `.j2` files are rendered:

- top-level files, for example `.env.j2` or `config.conf.j2`
- files anywhere under `config/` or `secrets/`

Application template directories such as `controller/templates/` are copied
unchanged and are not rendered. This keeps a stack's own source templates
safe.

If a rendered file must be readable by a container that runs as another user,
adjust the stack directory ownership or use a group that both the deploy user
and the container share. Rendered files default to `0640`; do not weaken that
for `.env` files.

The recursive copy still syncs the `.j2` files to the host, but only the
rendered file without the suffix contains values. Do not commit a plaintext
`.env` next to a `.env.j2`. The role fails the play when it sees both, because
the rendered file would silently win while the plaintext file still leaked
into the source tree and git history.

Ansible renders `.j2` files; Docker Compose reads the rendered `.env`:

- `{{ vault_example_password }}` is resolved by Ansible at deploy time.
- `${EXAMPLE_PORT}` in a compose file is resolved by Compose from `.env`.

Do not use `${...}` inside `.env.j2` for vault values. If a file needs a
literal `{{` or `{%`, wrap that section in `{% raw %}...{% endraw %}`.

The explicit `stack.env` dict remains supported for small per-host values.
When both are present, the `.j2` renderer runs after the dict renderer and
wins.

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
