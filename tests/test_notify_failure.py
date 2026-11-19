#!/usr/bin/env python3
"""Behaviour checks for roles/notifications/files/hsp-notify-unit-failure.

The wrapper is run against a fake `journalctl` and a fake `hsp-notify`, so
the test covers the argument contract, the journal tail in the body, the
size cap and the "journal unavailable" path without touching a real journal.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "roles" / "notifications" / "files" / "hsp-notify-unit-failure"

FAKE_NOTIFY = """#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["NOTIFY_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
"""

FAKE_JOURNALCTL = """#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["JOURNAL_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")

if os.environ.get("JOURNAL_FAIL") == "1":
    sys.exit(1)

sys.stdout.write(open(os.environ["JOURNAL_TEXT"], encoding="utf-8").read())
"""


def run(root: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    merged = dict(os.environ)
    merged.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=merged,
        capture_output=True,
        text=True,
    )


def calls(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        notify = root / "hsp-notify"
        notify.write_text(FAKE_NOTIFY)
        notify.chmod(0o755)
        journalctl = root / "journalctl"
        journalctl.write_text(FAKE_JOURNALCTL)
        journalctl.chmod(0o755)

        notify_log = root / "notify.log"
        journal_log = root / "journal.log"
        journal_text = root / "journal.txt"
        journal_text.write_text(
            "hsp-db-dump: sqlite bta: SQLite database not found: /srv/data/bta/data/bta.db\n"
            "Error running pre-everything hook\n"
        )

        env = {
            "NOTIFY_BIN": str(notify),
            "JOURNALCTL": str(journalctl),
            "NOTIFY_LOG": str(notify_log),
            "JOURNAL_LOG": str(journal_log),
            "JOURNAL_TEXT": str(journal_text),
        }

        # Normal failure: the wrapper asks for the last lines of the unit's
        # journal and embeds them in the body.
        result = run(root, env, "borgmatic.service")
        if result.returncode != 0:
            raise SystemExit(f"wrapper failed on a normal run: {result.stderr}")

        queries = calls(journal_log)
        expected_query = ["-u", "borgmatic.service", "-n", "6", "--no-pager", "-o", "cat"]
        if queries != [expected_query]:
            raise SystemExit(f"unexpected journalctl call: {queries}")

        sent = calls(notify_log)
        if len(sent) != 1:
            raise SystemExit(f"expected exactly one notification, got: {sent}")
        args = sent[0]
        if args[0] != "--priority" or args[1] != "high":
            raise SystemExit(f"failure notification lost its priority: {args}")
        if args[2] != "--tags" or args[3] != "rotating_light,borgmatic.service":
            raise SystemExit(f"unexpected tags: {args}")
        if not args[4].startswith("systemd unit failed: borgmatic.service on "):
            raise SystemExit(f"unexpected subject: {args[4]}")
        if "SQLite database not found" not in args[5]:
            raise SystemExit(f"journal tail missing from the body: {args[5]}")
        if "systemctl status borgmatic.service" not in args[5]:
            raise SystemExit(f"body lost the check hint: {args[5]}")

        # An oversized journal must be cut down instead of being rejected by
        # ntfy, and the cut must keep the newest lines.
        journal_text.write_text("old line\n" + ("x" * 4000) + "\nnewest line\n")
        run(root, env, "borgmatic.service")
        args = calls(notify_log)[-1]
        body = args[5]
        if len(body) > 1400:
            raise SystemExit(f"body was not capped: {len(body)} characters")
        if "[truncated]" not in body or "newest line" not in body:
            raise SystemExit("truncated body dropped the newest lines")

        # An unreadable journal must not stop the alert.
        env["JOURNAL_FAIL"] = "1"
        result = run(root, env, "borgmatic.service")
        if result.returncode != 0:
            raise SystemExit(f"wrapper failed without a journal: {result.stderr}")
        args = calls(notify_log)[-1]
        if "systemd unit failed" not in args[4]:
            raise SystemExit("missing journal suppressed the notification")

        # Without a unit argument there is nothing to report.
        before = len(calls(notify_log))
        result = run(root, env)
        if result.returncode != 2:
            raise SystemExit(f"missing unit should exit 2, got {result.returncode}")
        if len(calls(notify_log)) != before:
            raise SystemExit("missing unit still sent a notification")

    print("unit failure notification tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
