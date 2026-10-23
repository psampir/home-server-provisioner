# laptop_power

Generic power settings for laptops that run as servers. The role does not
assume a vendor or a model: every hardware path, module, and value is a
variable. Disabled by default.

## What it does

1. Writes a `systemd-logind` drop-in that controls lid-switch behaviour.
   On a headless laptop the usual setting is `ignore`, so closing the lid
   does not suspend the host.
2. Optionally loads a kernel module and writes a battery charge limit to a
   sysfs attribute.
3. Installs a oneshot systemd service that reapplies the battery limit at
   boot, because the attribute is not persistent across reboots.
4. Applies the battery limit immediately during provisioning and restarts
   `systemd-logind` when the lid drop-in changes.

## Variables

| Variable | Default | Description |
|---|---|---|
| `laptop_power_enabled` | `false` | Enable the role |
| `laptop_power_lid_switch` | empty | `HandleLidSwitch` value; empty leaves it unmanaged |
| `laptop_power_lid_switch_external_power` | same as `laptop_power_lid_switch` | Value on external power |
| `laptop_power_lid_switch_docked` | `ignore` | Value when docked |
| `laptop_power_battery_care_sysfs` | empty | Sysfs attribute to write |
| `laptop_power_battery_care_value` | `50` | Value written verbatim to the attribute |
| `laptop_power_battery_care_module` | empty | Kernel module to load first |
| `laptop_power_logind_dropin` | `/etc/systemd/logind.conf.d/10-hsp-lid.conf` | Drop-in path |
| `laptop_power_battery_service` | `laptop-battery-care.service` | Unit that reapplies the limit at boot |

## Battery attributes

The role writes one value to one sysfs attribute. The correct path and value
depend on the hardware. Common examples:

| Attribute | Typical value | Hardware |
|---|---|---|
| `/sys/class/power_supply/BAT0/charge_control_end_threshold` | `50` to `100` | Many modern laptops (ThinkPad, Framework, some Dell and ASUS) |
| `/sys/devices/platform/sony-laptop/battery_care_limiter` | `50` or `80` | Sony laptop with the `sony_laptop` module |
| `/sys/class/power_supply/BAT0/charge_behaviour` | `auto`, `inhibit-charge` | Drivers that expose a behaviour instead of a percentage |

Use the value the driver expects. The role does not translate percentages
or validate hardware-specific ranges.

## Generic example

Limit charging to 80 percent on a laptop that exposes the standard
threshold, and ignore the lid switch on battery and external power:

```yaml
laptop_power_enabled: true
laptop_power_lid_switch: ignore
laptop_power_lid_switch_external_power: ignore
laptop_power_lid_switch_docked: ignore
laptop_power_battery_care_sysfs: /sys/class/power_supply/BAT0/charge_control_end_threshold
laptop_power_battery_care_value: "80"
```

## Sony laptop example

```yaml
laptop_power_enabled: true
laptop_power_lid_switch: ignore
laptop_power_lid_switch_external_power: ignore
laptop_power_lid_switch_docked: ignore
laptop_power_battery_care_module: sony_laptop
laptop_power_battery_care_sysfs: /sys/devices/platform/sony-laptop/battery_care_limiter
laptop_power_battery_care_value: "50"
```

Check the current value:

```bash
cat /sys/devices/platform/sony-laptop/battery_care_limiter
```

Check the effective lid policy after provisioning:

```bash
systemd-analyze cat-config systemd/logind.conf | grep HandleLidSwitch
```

## Notes

- The role does not install a desktop power manager. It relies on
  `systemd-logind`, which is present on a standard Debian install.
- Restarting `systemd-logind` can interrupt an active graphical session.
  Do not run this role on a workstation with a logged-in desktop user.
- The battery service is `Type=oneshot` with `RemainAfterExit=yes`, so it
  stays active between runs and does not reapply the value on every play.
- A laptop may also suspend on idle through a desktop environment. This
  role only changes the lid switch and the battery limit.
- If the configured sysfs attribute does not exist, the role fails with its
  path and a hint to check the kernel module. This catches a wrong path
  early instead of silently doing nothing.
