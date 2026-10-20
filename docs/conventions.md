# Conventions

Short, factual rules this repository follows. They are why `ansible-lint`
(profile `production`) passes without per-rule skips, and why a role's
interface is readable from its directory alone.

## Role names

`snake_case`. **Plural** when the role manages a collection of things -
`systemd_units`, `scheduled_jobs`, `custom_scripts`, `network_mounts`.
**Singular** for a single concern - `firewall`, `swap`, `wireguard`,
`borgmatic`.

## Variables

Every variable a role introduces is prefixed with the role name (`<role>_`)
and declared in that role's `defaults/main.yml` (or `vars/` when the author
must control it). Tasks that only *use* a name are not enough: `ansible-lint`
lints declared names, and an undeclared variable is invisible in the role's
public interface.

### Deliberate exceptions: inventory contracts

A handful of names are per-host data consumed by several roles rather than
input to one role. They are intentionally **not** prefixed:

| Name | Consumers | Why it stays unprefixed |
|---|---|---|
| `vpn_ip` | `wireguard`, `firewall`, `dnsmasq`, `network_mounts`, stacks | One address per host, read by many roles and written by every inventory. |
| `bootstrap_user` | `bootstrap.yml`, `base`, `admin_user` | The only account that exists before `admin_user` is created. |
| `ansible_*` | Ansible itself | Connection variables owned by the inventory/Ansible, not by a role. |

Renaming these would break every existing inventory and gain nothing, so they
are documented exceptions instead.

## Backward-compatible renames

When a variable has to be renamed, declare the **new** name in `defaults/` and
default it from the old one, then use only the new name in tasks:

```yaml
# Device GRUB is installed to. Empty = auto-detect.
base_grub_install_device: "{{ grub_install_device | default('') }}"
```

Existing inventories that still set the old name keep working, and the old
name is documented as an accepted alias wherever users are likely to set it
(example `group_vars`, the role README).

## Templates and files

`<role>.<purpose>.<ext>.j2` - `scheduled_jobs.service.j2`,
`borgmatic.timer-dropin.conf.j2`, `base/templates/99-hsp.conf.j2`. Where the
rendered target differs from the template name (systemd drop-ins, files
carrying the `hsp-` prefix), the destination documented in the task and role
README is the source of truth.

## Role pairing

`borgmatic` (backup **source**) and `borg_repo` (backup **target**) are two
different tools in one pipeline, not a naming inconsistency. They are paired,
not merged, and each README states which side it is.

## Makefile targets

`<domain>-<action>`: `wireguard-keys`, `wireguard-render`, `vault-init`,
`vault-edit`, `test-env-create`, `test-smoke`. Short aliases are allowed where
they are already referenced widely in docs (`wg-render`), but the canonical
`<domain>-<action>` name is what new documentation should use, and every alias
carries a `##` help comment so `make help` lists it.
