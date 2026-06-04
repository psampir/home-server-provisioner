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
