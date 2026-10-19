# WireGuard clients

How to put a phone, laptop, or tablet on the VPN - and how that differs
from provisioning a server.

## Managed peers vs external clients

Two very different things share the same tunnel:

| | Managed peer | External client |
| --- | --- | --- |
| What it is | A server in your Ansible inventory | A phone/laptop you hold in your hand |
| Declared in | `hosts.yml` + `host_vars/` with `vpn_ip` | `wireguard_clients` in `group_vars/all/main.yml` |
| Keys | Generated on the host, private key never leaves it | Generated on the controller, stored in the vault |
| Config | `wg0.conf` rendered on the host | `.conf` + QR rendered on demand for import |
| Ansible reachability | The controller connects to it | None - it is not managed |
| Address range | `.2` - `.19` | `.20` - `.254` |

An external client exists on the hub **only** as a `[Peer]` block with
`AllowedIPs = <vpn_ip>/32`. It is never an Ansible host, never receives
a play, and never appears in `groups['servers']`.

## Declaring a client

Add an entry to `configs/<ENV>/inventory/group_vars/all/main.yml`:

```yaml
wireguard_clients:
  - { name: phone, vpn_ip: 10.10.0.20 }
  - { name: laptop,  vpn_ip: 10.10.0.21, allowed_ips: "0.0.0.0/0" }
```

Only `name` and `vpn_ip` are required. The wireguard role asserts that
each entry has both, that the address is inside `wireguard_subnet`, and
that no two hosts or clients share an address.

Do **not** put keys in this list. They are stored separately, encrypted,
under the vault key `vault_wireguard_client_keys`:

```yaml
vault_wireguard_client_keys:
  phone:
    privkey: "..."
    pubkey:  "..."
    psk:     "..."
```

The example inventory already re-exports that vaulted map so the role can
see it:

```yaml
wireguard_client_keys: "{{ vault_wireguard_client_keys | default({}) }}"
```

## Key management: `scripts/wg-ensure-keys.py`

`make provision` runs the script as a pre-hook (`wireguard-keys`), and
you can run it alone:

```bash
make wireguard-keys
```

It performs a three-way reconciliation between `wireguard_clients` and
the vault map:

1. **Generate** `privkey`/`pubkey`/`psk` for every client missing from
   the vault (`wg genkey`, `wg pubkey`, `wg genpsk`).
2. **Prune** vault entries whose name disappeared from
   `wireguard_clients`.
3. **Re-encrypt** `vault.yml` in place, then **auto-commit** it into the
   `configs/<ENV>/` git repo with a message such as
   `wireguard keys: add phone; prune old-tablet`.

It requires `wg` and `ansible-vault` on `PATH`, and
`$ANSIBLE_VAULT_PASSWORD_FILE` pointing at the environment's vault
password (the Makefile exports `configs/<ENV>/.vault_pass`).

### Prune safety

Pruning is deliberately conservative:

- If the vault lives in a git repo and that repo has **uncommitted
  changes other than `vault.yml`**, the script refuses to prune. This is
  the "typo in the client name" guard: mid-edit, a client looks deleted,
  and silently destroying its key would be unrecoverable.
- If the vault is not in a git repo at all (e.g. the test environment),
  there is no history to lose, so pruning proceeds unconditionally.
- The `--no-commit` flag skips the auto-commit step; `make test-provision`
  passes it so the test env does not create commits. `make wireguard-keys`
  accepts it via `WG_KEYS_FLAGS=--no-commit`.

Every vault change is a commit, so an accidental prune is recoverable:

```bash
git -C configs/prod log -- inventory/group_vars/all/vault.yml
git -C configs/prod show <sha>:inventory/group_vars/all/vault.yml
```

## Rendering the client artifact

`make provision` deploys the hub's `[Peer]` sections but **never writes
private-key material to the controller's disk**. Onboarding is a
separate, on-demand step:

```bash
make wg-render                 # default env
make wg-render ENV=prod        # explicit
```

This runs `playbooks/wireguard_clients.yml`, which targets the hub only,
derives its public key from `/etc/wireguard/wg0.privkey`, and renders on
the controller:

```text
build/<env>/wireguard/<name>.conf    mode 0600
build/<env>/wireguard/<name>.png     mode 0600 (if qrencode is installed)
```

The directory itself is created mode `0700`, is partitioned per
environment via `HSP_ENV`, and is gitignored. QR generation is on by
default (`wireguard_generate_qr: true`); if `qrencode` is missing the
play prints an install hint and skips the PNGs.

**Delete the output once the device is set up.** These files contain
plaintext private keys:

```bash
rm -rf build/
```

Distribute the `.conf` by `scp`, or scan the PNG with the WireGuard app
(which is why the QR exists at all).

## Split tunnel vs full tunnel

The default is a **split tunnel**: only VPN traffic goes through the
tunnel.

```yaml
wireguard_client_default_allowed_ips: "{{ wireguard_subnet }}"   # 10.10.0.0/24
```

The client can reach the hub and all managed peers by `vpn_ip`, and
everything else uses its normal connection. This is the right choice for
phones: it is fast, it does not break captive portals, and it does not
push all your mobile traffic through a home server.

For a **full tunnel**, set `allowed_ips` on the individual client:

```yaml
wireguard_clients:
  - { name: laptop-travel, vpn_ip: 10.10.0.22, allowed_ips: "0.0.0.0/0" }
```

All traffic - IPv4 - then exits through the hub. The hub's NAT rule
(`wireguard_enable_nat`) masquerades it out of the WAN interface, so this
works without any extra configuration. This is the option to use on
untrusted networks where you want the client's traffic to appear to come
from home.

`allowed_ips` is rendered verbatim into the `.conf`; it does not change
what the hub allows, only what the client routes into the tunnel.

## DNS

Every generated client config gets a DNS line:

```ini
DNS        = {{ wireguard_client_dns }}    # defaults to wireguard_hub_ip
```

Because external clients run their own resolver stack (iOS/Android/
NetworkManager all honour `DNS =`), `wg-quick` can manage DNS for them
safely - unlike on server peers, where `dns_client` owns
`/etc/resolv.conf`. See
[`docs/networking.md`](networking.md#why-wg-quick-must-not-manage-peer-dns)
for that failure mode.

Together with the default split tunnel this gives you local names over
the VPN: `whoami.home` resolves through dnsmasq on the hub, while
everything else is answered by whatever resolver the device normally
uses.

Set `wireguard_client_dns` to another address if you want clients to use
a different resolver - but if it is behind the tunnel, remember that it
must be reachable with the client's `AllowedIPs`.

## Preshared keys

Every generated client also gets a `psk` from `wg genpsk`, and the
templates emit it when present:

```ini
PresharedKey = <psk>
```

The same value is written into the hub's `[Peer]` block, so the extra
symmetric layer is always in effect. It is not post-quantum cryptography,
but it does mean an attacker who steals a device's private key still
needs the PSK from the vault. There is nothing to configure - just let
the script manage `psk` alongside the keypair.

## Adding and removing clients

**Add** a phone:

1. Append `{ name: phone-x, vpn_ip: 10.10.0.23 }` to `wireguard_clients`.
2. `make provision` - generates the keys, commits the vault, and adds the
   `[Peer]` block to the hub.
3. `make wg-render`, scan the QR, then `rm -rf build/`.

**Remove** a phone:

1. Delete its entry from `wireguard_clients`.
2. `make provision` - the script prunes the vault entry (if the config
   repo is otherwise clean) and the hub config is re-rendered without
   that peer.
3. Optionally re-render if you keep other clients' artifacts around.

Removing a peer only revokes it from the hub's config; the device keeps
its (now useless) `.conf` and private key. If a device is lost rather
than retired, rotate anything else that was reachable through the
tunnel - the VPN was never the only credential.

**Renaming** a client looks like remove + add. Do that in a single
committed change so the prune safeguard does not block you: the script
refuses to prune while the config repo has unrelated uncommitted
changes.

## Related reading

- [`docs/networking.md`](networking.md) - topology, addressing, DNS, and
  firewall behaviour
- [`roles/wireguard/README.md`](../roles/wireguard/README.md) - role
  reference, including the peer-DNS regression check
- [`playbooks/wireguard_clients.yml`](../playbooks/wireguard_clients.yml)
  - what `make wg-render` actually runs
- [`scripts/wg-ensure-keys.py`](../scripts/wg-ensure-keys.py) - key
  generation and pruning implementation
