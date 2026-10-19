# firewall

UFW-based host firewall: default-deny incoming, always-allow SSH, plus a
variable-driven allowlist. **Fully reconciling** - a rule removed from
`firewall_allow_rules` is deleted from ufw on the next run.

## What it does

1. Installs and enables `ufw`.
2. Sets default policies (`incoming: deny`, `outgoing: allow`) and the
   logging level.
3. Always allows the SSH port (`firewall_ssh_port`) - lockout protection.
4. Applies every entry in `firewall_allow_rules` as a `ufw allow` rule.
5. **Reconciles**: deletes any rule this role previously added but that no
   longer appears in `firewall_allow_rules`.

### How reconciliation works

The role tracks the rules **it** manages in a per-host manifest
(`firewall_manifest_path`, default
`/var/lib/home-server-provisioner/firewall.manifest`). Each managed rule
is stored as a canonical key `rule;port;proto;from` - the comment is
deliberately excluded, so editing a comment is not a change. On each run
the role diffs the current set against the manifest and `ufw delete`s the
difference.

Only rules added through `firewall_allow_rules` are tracked. Rules added
by **other roles** (`caddy`, `dnsmasq`, `wireguard`) and the always-on
**SSH** rule are never in the manifest and are never pruned. The delete
step additionally refuses to touch anything on `firewall_ssh_port`, as a
second layer of lockout protection.

## What it does NOT do

- **Does not reconcile rules it didn't create.** Manually-added ufw rules,
  or rules added by other roles, are left untouched by design (that is how
  `caddy`/`dnsmasq`/`wireguard` coexist with this role).
- **No `ufw reset`.** The firewall is never torn down, so there is no
  window where the host is left open or unreachable mid-run.

## Migration note

The reconciliation manifest is written on the first run of this version.
Rules added by an **older** (non-reconciling) version of this role are not
recorded in the manifest, so the *first* run after upgrading will not
prune a rule that you remove from `firewall_allow_rules` at the same time
- there is no record that the role ever owned it. Remove such a stale rule
once by hand (`ufw delete allow <port>/<proto>`); from then on
reconciliation is automatic.

## Docker bypasses UFW

**A published container port is not protected by this role.** Docker
manipulates iptables/nftables directly: `docker run -p` / `ports:` in
Compose inserts DNAT rules in the `nat` table and its own filter chains,
and the resulting traffic is forwarded straight to the container. It
never traverses UFW's `INPUT` chain, so no `ufw` rule - allow *or* deny -
applies to it. This is upstream Docker behaviour, not a bug in this role.

The practical consequence: on a host that runs Docker, `ufw status`
showing only `22/tcp` and `443/tcp` does **not** mean the host only
exposes those ports. A stack that publishes `8080:8080` is reachable on
`8080` from anywhere the host is reachable, even though UFW denies
everything by default.

Workarounds, in order of preference:

**(a) Bind published ports to a specific address.** Instead of the
default `0.0.0.0`, publish on the peer's WireGuard address or on
loopback:

```yaml
services:
  whoami:
    ports:
      - "10.10.0.2:8080:8080"   # only reachable over the VPN tunnel
  admin:
    ports:
      - "127.0.0.1:9090:9090"   # only reachable from this host
```

This is the simplest fix and needs no firewall changes: the port is
never bound on the public interface in the first place.

**(b) Put a reverse proxy in front.** Publish nothing (or only
`127.0.0.1`) and let Caddy - which does respect UFW because it is a
normal host process - terminate and route traffic. See
[`docs/caddy.md`](../../docs/caddy.md).

**(c) Manage the `DOCKER-USER` chain.** If you need host-level
filtering of container traffic, add rules to Docker's `DOCKER-USER`
chain, which is evaluated before Docker's own rules:

```bash
ufw route allow in on wg0 out on docker0
# or, at the iptables level:
iptables -I DOCKER-USER -i eth0 ! -s 10.10.0.0/24 -j DROP
```

Rules in `DOCKER-USER` are **not** managed by this role and are not
tracked in the reconciliation manifest - you own their lifecycle.

**This role does NOT manage `DOCKER-USER`.** It only configures the UFW
`INPUT` policy and `firewall_allow_rules`. Treat every `ports:` entry in
a Compose stack as internet-facing unless it is explicitly bound to a
private address.

## Variables

```yaml
firewall_default_incoming: deny
firewall_default_outgoing: allow
firewall_logging: low
firewall_ssh_port: 22
firewall_allow_rules: []
firewall_manifest_path: /var/lib/home-server-provisioner/firewall.manifest
```

### Per-rule schema

| key       | required | default | notes                                   |
|-----------|----------|---------|-----------------------------------------|
| `port`    | yes      | -       | Port or `start:end` range.              |
| `proto`   | no       | `tcp`   | `tcp`, `udp`, or `any`.                 |
| `rule`    | no       | `allow` | `allow` or `deny`.                      |
| `from`    | no       | (any)   | Source CIDR/IP to scope the rule.       |
| `comment` | no       | -       | Free text; not part of the rule identity. |

### Example

```yaml
firewall_allow_rules:
  - { port: 80,    proto: tcp, comment: "HTTP" }
  - { port: 443,   proto: tcp, comment: "HTTPS" }
  - { port: 9090,  proto: tcp, from: "10.0.0.0/24", comment: "Internal admin" }
```
