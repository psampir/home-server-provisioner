# forgejo (example stack)

This is an **example**, not a deployment target. It demonstrates the
host-overlay layout consumed by `roles/compose_deploy`:

```
configs/<env>/stacks/<inventory_hostname>/<stack>/
```

`make init-config` copies this directory into the new environment. If the
environment inventory has a host named `home-app`, the stack is deployed to
`/opt/stacks/forgejo/` there on the next `make provision`.

Before using it:

- Change `FORGEJO__server__ROOT_URL` to the public URL you will serve
  through Caddy (or delete the stack if you do not need Forgejo).
- Review the published ports (`3000` for HTTP, `2222` for SSH) and the
  bind-mounted `./data` and `./config` directories, which are created
  relative to the on-host stack directory.
- Pin the image tag deliberately when upgrading; this example uses a fixed
  version, never `latest`.
