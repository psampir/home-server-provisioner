# Conventions

Short, factual rules this repository follows. They are why `ansible-lint`
(profile `production`) passes with only two documented `args[module]`
exceptions for `community.general.ufw`, and why a role's interface is
readable from its directory alone.

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
| `vpn_ip` | `wireguard`, `dnsmasq`, `borgmatic`, stacks | One address per host, read by many roles and written by every inventory. |
| `bootstrap_user` | `bootstrap.yml`, `base`, `admin_user` | The only account that exists before `admin_user` is created. |
| `ansible_*` | Ansible itself | Connection variables owned by the inventory/Ansible, not by a role. |

Renaming these would break every existing inventory and gain nothing, so they
are documented exceptions instead.

## No legacy aliases

Backward-compatible aliases are not kept: every role, variable, and make
target has exactly one name. A rename is a plain rename: no compatibility shim, no
`default(old_name)` indirection, no deprecated spelling kept around. The old
name stops working in the same commit that introduces the new one, and every
reference in docs, inventory examples, and scripts is updated with it.

## Templates and files

Prefer `<role>.<purpose>.<ext>.j2` for new templates, for example
`scheduled_jobs.service.j2`, `borgmatic.timer-dropin.conf.j2`, and
`base/templates/99-hsp.conf.j2`. Some templates mirror an upstream package
path instead, such as `ups.conf.j2` or `resolv.conf.j2`; the destination
documented in the task and role README is the source of truth, not the
filename convention.

## Role pairing

`borgmatic` (backup **source**) and `borg_repo` (backup **target**) are two
different tools in one pipeline, not a naming inconsistency. They are paired,
not merged, and each README states which side it is.

## Makefile targets

`<domain>-<action>`: `wireguard-keys`, `wireguard-render`, `vault-init`,
`vault-edit`, `test-env-create`, `test-smoke`. There are no short aliases - the
canonical `<domain>-<action>` name is the only name, and every target carries a
`##` help comment so `make help` lists it.

Role tags mirror role names, so `make provision TAGS=<role>[,<role>...]` re-runs
a subset (for example `TAGS=gatus`). `compose_deploy` also carries `stacks`, and
`local_ssh_config` also carries `ssh_config`. Tagged runs skip the
`wireguard-keys` prerequisite.

## Public repository hygiene

This repository is public; real deployments are not. Everything committed,
tagged, released or discussed here is world-readable forever, including
release notes, annotated tag messages and commit messages. Write for an
audience that has never seen the fleet:

- **Placeholders only.** `app1`, `backup1`, `hub`, `ENV=prod`, `<host>`,
  `example.internal`, `192.168.50.x` and `198.51.100.x` (RFC 5737). Never a
  real host name, environment name, internal domain, stack name, data path,
  disk serial, MAC, VPN peer address or public IP.
- **Release notes describe the mechanism, not the rollout.** "Verified on a
  real deployment" is enough; "verified on <host>" maps the fleet.
- **Incidents lose their identifiers, not their lesson.** Keep dates, error
  text from upstream projects, timings and counts; drop which host, which
  stack and which path.
- **The same rule applies to commit messages and tag messages**, because both
  are public in the same way and survive in clones and mirrors.

Private inventories, host variables and operational status live in separate
private repositories; they are never referenced by name here.
