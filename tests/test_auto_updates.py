#!/usr/bin/env python3
"""Checks for the unattended-upgrades origin pattern.

Debian security suites are named <codename>-security, so a pattern without
the suffix matches nothing. The dry-run on a host shows the candidate being
adjusted back to the installed version, which is how this was found.
"""

from __future__ import annotations

import sys
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[1]
DEFAULTS = REPO / "roles" / "auto_updates" / "defaults" / "main.yml"
TEMPLATE = REPO / "roles" / "auto_updates" / "templates" / "50unattended-upgrades.j2"


def main() -> int:
    defaults = yaml.safe_load(DEFAULTS.read_text())
    origins = defaults["auto_updates_origins"]
    assert origins, origins

    security = [origin for origin in origins if "label=Debian-Security" in origin]
    assert security, origins
    for origin in security:
        assert "codename=${distro_codename}-security" in origin, origin

    rendered = jinja2.Template(TEMPLATE.read_text()).render(
        auto_updates_origins=origins,
        auto_updates_autofix_interrupted_dpkg=True,
        auto_updates_remove_unused_dependencies=True,
        auto_updates_remove_unused_kernel_packages=True,
        auto_updates_enable_reboot=False,
        auto_updates_reboot_time="03:00",
    )
    assert "Unattended-Upgrade::Origins-Pattern" in rendered
    assert "codename=${distro_codename}-security" in rendered
    assert 'Unattended-Upgrade::Remove-Unused-Kernel-Packages "true"' in rendered

    print("test-auto-updates: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
