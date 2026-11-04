#!/usr/bin/env python3
"""Checks for the generated OliveTin sudoers file.

The template is rendered with the role defaults loaded from YAML, so the
test fails if the map of allowed arguments and the installed wrapper list
drift apart.
"""

from __future__ import annotations

import sys
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[1]
DEFAULTS = REPO / "roles" / "olivetin_agent" / "defaults" / "main.yml"
TEMPLATE = REPO / "roles" / "olivetin_agent" / "templates" / "90-olivetin.j2"


def render(defaults: dict, **overrides) -> str:
    context = {
        "olivetin_agent_user": defaults["olivetin_agent_user"],
        "olivetin_agent_wrappers": defaults["olivetin_agent_wrappers"],
        "olivetin_agent_wrapper_commands": defaults["olivetin_agent_wrapper_commands"],
        "olivetin_agent_extra_sudo_commands": defaults["olivetin_agent_extra_sudo_commands"],
    }
    context.update(overrides)
    return jinja2.Template(TEMPLATE.read_text()).render(**context)


def command_line(rendered: str) -> str:
    lines = [line for line in rendered.splitlines() if "NOPASSWD" in line]
    assert len(lines) == 1, rendered
    return lines[0]


def main() -> int:
    defaults = yaml.safe_load(DEFAULTS.read_text())

    # The defaults must be self-consistent.
    assert set(defaults["olivetin_agent_wrappers"]) <= set(
        defaults["olivetin_agent_wrapper_commands"]
    ), "olivetin_agent_wrappers contains a wrapper missing from the command map"

    rendered = render(defaults)
    assert rendered.startswith("# Managed by Ansible - do not edit manually.\n"), rendered

    expected = [
        "/usr/local/sbin/hsp-apt check",
        "/usr/local/sbin/hsp-apt upgrade",
        "/usr/local/sbin/hsp-apt autoremove-check",
        "/usr/local/sbin/hsp-apt autoremove",
        "/usr/local/sbin/hsp-needrestart",
        "/usr/local/sbin/hsp-reboot schedule",
        "/usr/local/sbin/hsp-reboot cancel",
        "/usr/local/sbin/hsp-backup-check",
        "/usr/local/sbin/hsp-journal-vacuum",
        "/usr/local/sbin/hsp-etckeeper",
        "/usr/local/sbin/hsp-smart short",
        "/usr/local/sbin/hsp-smart status summary",
        "/usr/local/sbin/hsp-smart status full",
    ]
    assert command_line(rendered) == (
        "olivetin ALL=(root) NOPASSWD: " + ", ".join(expected)
    ), command_line(rendered)
    assert "hsp-apt autoremove" in rendered
    assert "hsp-smart status summary" in rendered

    rendered = render(
        defaults,
        olivetin_agent_wrappers=["hsp-apt"],
        olivetin_agent_extra_sudo_commands=["/usr/local/bin/moj-skrypt restart"],
    )
    assert command_line(rendered) == (
        "olivetin ALL=(root) NOPASSWD: "
        "/usr/local/sbin/hsp-apt check, "
        "/usr/local/sbin/hsp-apt upgrade, "
        "/usr/local/sbin/hsp-apt autoremove-check, "
        "/usr/local/sbin/hsp-apt autoremove, "
        "/usr/local/bin/moj-skrypt restart"
    ), command_line(rendered)
    for wrapper in defaults["olivetin_agent_wrapper_commands"]:
        if wrapper != "hsp-apt":
            assert f"/usr/local/sbin/{wrapper}" not in rendered, rendered

    assert "*" not in rendered
    assert "?" not in rendered

    # An empty command list must still produce a file visudo accepts: only
    # the comment, no dangling NOPASSWD rule.
    rendered = render(
        defaults,
        olivetin_agent_wrappers=[],
        olivetin_agent_extra_sudo_commands=[],
    )
    assert rendered == "# Managed by Ansible - do not edit manually.\n", repr(rendered)

    print("test_olivetin_agent: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
