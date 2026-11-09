#!/usr/bin/env python3
"""Behaviour checks for roles/image_updates/files/hsp-image-updates.

The script is pointed at a fake `docker` (canned `compose config` JSON per
stack), a fake notify binary that records its arguments, and a local HTTP
registry. No daemon, no network and no real notification are involved.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "roles" / "image_updates" / "files" / "hsp-image-updates"

FAKE_DOCKER = """#!/bin/sh
project=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "--project-directory" ]; then project="$arg"; fi
  prev="$arg"
done
name=$(basename "$project")
file="$FAKE_DOCKER_FIXTURES/$name.json"
if [ ! -f "$file" ]; then
  echo "compose config failed for $name" >&2
  exit 1
fi
cat "$file"
"""

FAKE_NOTIFY = """#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["NOTIFY_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
"""

PAGE_SIZE = 2


def digest_for(repo: str, tag: str) -> str:
    return "sha256:" + hashlib.sha256(f"{repo}:{tag}".encode()).hexdigest()


def serve_registry(
    tags_by_repo: dict[str, list[str]],
    releases_by_project: dict[str, list[dict]] | None = None,
    flaky_manifests: dict[tuple[str, str], int] | None = None,
):
    """Start a fake registry and return (server, base URL, manifest request counts).

    `flaky_manifests` maps a (repo, tag) to how many manifest requests should
    answer 429 (with `Retry-After: 0`) before serving normally. The returned
    counter dict records every manifest request, so a test can prove that the
    reporter retried exactly as often as intended.
    """
    releases_by_project = releases_by_project or {}
    flaky = dict(flaky_manifests or {})
    manifest_hits: dict[tuple[str, str], int] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # keep the test output quiet
            pass

        def _send(self, status: int, body: bytes, headers: dict[str, str]) -> None:
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: dict, headers: dict[str, str] | None = None) -> None:
            self._send(
                status,
                json.dumps(payload).encode(),
                {"Content-Type": "application/json", **(headers or {})},
            )

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            parts = urllib.parse.urlsplit(self.path)
            path = parts.path
            query = urllib.parse.parse_qs(parts.query)

            if path.startswith("/repos/") and path.endswith("/releases"):
                project = path[len("/repos/") : -len("/releases")]
                releases = releases_by_project.get(project)
                if releases is None:
                    self._json(404, {"message": "Not Found"})
                    return
                self._json(200, releases)
                return

            if path.endswith("/tags/list"):
                repo = path[len("/v2/") : -len("/tags/list")]
                tags = tags_by_repo.get(repo)
                if tags is None:
                    self._json(404, {"errors": [{"code": "NAME_UNKNOWN"}]})
                    return
                last = query.get("last", [""])[0]
                start = 0
                if last in tags:
                    start = tags.index(last) + 1
                page = tags[start : start + PAGE_SIZE]
                headers = {}
                if page and start + PAGE_SIZE < len(tags):
                    headers["Link"] = (
                        f'</v2/{repo}/tags/list?n={PAGE_SIZE}&last={page[-1]}>; rel="next"'
                    )
                self._json(200, {"name": repo, "tags": page}, headers)
                return

            if "/manifests/" in path:
                repo, tag = path[len("/v2/") :].split("/manifests/", 1)
                tag = urllib.parse.unquote(tag)
                key = (repo, tag)
                manifest_hits[key] = manifest_hits.get(key, 0) + 1
                if flaky.get(key, 0) > 0:
                    flaky[key] -= 1
                    self._json(
                        429,
                        {"errors": [{"code": "TOOMANYREQUESTS"}]},
                        {"Retry-After": "0"},
                    )
                    return
                if tag not in tags_by_repo.get(repo, []):
                    self._json(404, {"errors": [{"code": "MANIFEST_UNKNOWN"}]})
                    return
                body = json.dumps(
                    {
                        "schemaVersion": 2,
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    }
                ).encode()
                self._send(
                    200,
                    body,
                    {
                        "Content-Type": "application/vnd.oci.image.manifest.v1+json",
                        "Docker-Content-Digest": digest_for(repo, tag),
                    },
                )
                return

            self._json(404, {"errors": [{"code": "NOT_FOUND"}]})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", manifest_hits


class Case:
    """One isolated stack tree, config, fake binaries and registry."""

    def __init__(self, root: Path, registry_url: str) -> None:
        self.root = root
        self.registry_url = registry_url
        self.bin = root / "bin"
        self.bin.mkdir(parents=True)
        for name, body in (("docker", FAKE_DOCKER), ("hsp-notify", FAKE_NOTIFY)):
            path = self.bin / name
            path.write_text(body)
            path.chmod(0o755)
        self.stacks = root / "stacks"
        self.stacks.mkdir()
        self.fixtures = root / "fixtures"
        self.fixtures.mkdir()
        self.config = root / "image-updates.json"
        self.state = root / "state" / "image-updates.json"
        self.notify_log = root / "notify.log"
        self.write_config()

    def stack(self, name: str, services: dict) -> None:
        directory = self.stacks / name
        directory.mkdir()
        (directory / "compose.yaml").write_text("services: {}\n")
        (self.fixtures / f"{name}.json").write_text(json.dumps({"services": services}))

    def write_config(self, **overrides) -> None:
        config = {
            "stacks_dir": str(self.stacks),
            "state_file": str(self.state),
            "include_stacks": [],
            "exclude_stacks": [],
            "ignore_images": [],
            "include_major": True,
            "notify_when_current": False,
            "notify_bin": str(self.bin / "hsp-notify"),
            "notify_priority": "low",
            "notify_tags": "update_report,docker",
            "registry_timeout": 5,
            "compose_timeout": 10,
        }
        config.update(overrides)
        self.config.write_text(json.dumps(config))

    def run(self, *extra: str) -> subprocess.CompletedProcess:
        if self.notify_log.exists():
            self.notify_log.unlink()
        env = dict(os.environ)
        env["HSP_IMAGE_UPDATES_TEST_REGISTRY"] = self.registry_url
        env["HSP_IMAGE_UPDATES_TEST_GITHUB"] = self.registry_url
        env["FAKE_DOCKER_FIXTURES"] = str(self.fixtures)
        env["NOTIFY_LOG"] = str(self.notify_log)
        env["PATH"] = f"{self.bin}:{env.get('PATH', '')}"
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(self.config), *extra],
            env=env,
            capture_output=True,
            text=True,
        )

    def notifications(self) -> list[list[str]]:
        if not self.notify_log.exists():
            return []
        return [
            json.loads(line)
            for line in self.notify_log.read_text().splitlines()
            if line.strip()
        ]


def add_findings_stack(case: Case) -> None:
    case.stack(
        "alpha",
        {
            "web": {"image": "ghcr.io/acme/web:16-alpine"},
            "api": {"image": "nginx:2.11.7"},
            "pinned": {
                "image": "ghcr.io/acme/pinned:1.2.3@sha256:"
                + hashlib.sha256(b"old").hexdigest()
            },
            "env": {"image": "ghcr.io/acme/env:2.0.0"},
            # Pinned and outdated: the newer tag must replace the digest
            # finding, not appear next to it.
            "drift": {
                "image": "ghcr.io/acme/drift:2.0.0@sha256:"
                + hashlib.sha256(b"older").hexdigest()
            },
            "pg": {"image": "ghcr.io/acme/pg:14-vectorchord0.4.3-pg17"},
            "built": {"build": {"context": "."}, "image": "ghcr.io/acme/built:9.9.9"},
            "ignored": {"image": "ghcr.io/acme/ignored:1.0.0"},
        },
    )
    case.stack("beta", {"tool": {"image": "ghcr.io/acme/tool:v3.3.5"}})


RELEASES = {
    "acme/relapp": [
        {"tag_name": "v3.6.0", "prerelease": True},
        {"tag_name": "v3.4.0"},
        {"tag_name": "v3.3.5"},
        {"tag_name": "v2.9.0"},
    ]
}

TAGS = {
    "acme/web": ["15-alpine", "16-alpine", "17-alpine"],
    "library/nginx": ["2.11.7", "2.11.8"],
    "acme/pinned": ["1.2.3"],
    "acme/env": ["2.0.0", "2.0.1"],
    "acme/drift": ["2.0.0", "2.0.1"],
    "acme/pg": ["14-vectorchord0.4.3-pg17", "15-vectorchord0.4.3-pg17"],
    "acme/tool": ["v3.3.5", "v3.4.0"],
    "acme/current": ["1.2.3"],
    # Retry scenarios: "flaky" fails twice, "stuck" never recovers.
    "acme/flaky": ["2.0.0"],
    "acme/stuck": ["2.0.0"],
}

# The first two manifest requests for "flaky" answer 429; "stuck" has enough
# failures to outlast every attempt of the retry loop.
FLAKY_MANIFESTS = {("acme/flaky", "2.0.0"): 2, ("acme/stuck", "2.0.0"): 10}


def main() -> int:
    server, registry_url, manifest_hits = serve_registry(TAGS, RELEASES, FLAKY_MANIFESTS)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            # -- findings, digest drift, skip rules and one notification ---
            case = Case(root / "findings", registry_url)
            add_findings_stack(case)
            case.write_config(ignore_images=["ghcr.io/acme/ignored"])
            result = case.run()
            if result.returncode != 0:
                raise SystemExit(f"findings run failed: {result.stderr}")

            messages = case.notifications()
            if len(messages) != 1:
                raise SystemExit(f"expected one notification, got {messages!r}")
            args = messages[0]
            if args[0] != "--priority" or args[1] != "low":
                raise SystemExit(f"priority argument missing: {args!r}")
            if "--tags" not in args or "update_report,docker" not in args:
                raise SystemExit(f"tags argument missing: {args!r}")
            subject, body = args[-2], args[-1]
            if not subject.startswith("docker updates ") or not subject.endswith(
                ": 6 available"
            ):
                raise SystemExit(f"wrong subject: {subject!r}")

            expected = [
                "- api (alpha): nginx:2.11.7 -> nginx:2.11.8 (patch)",
                "- env (alpha): ghcr.io/acme/env:2.0.0 -> ghcr.io/acme/env:2.0.1 (patch)",
                "- drift (alpha): ghcr.io/acme/drift:2.0.0"
                " -> ghcr.io/acme/drift:2.0.1 (patch)",
                "- pinned (alpha): ghcr.io/acme/pinned:1.2.3 tag moved (digest)",
                "major:",
                "- web (alpha): ghcr.io/acme/web:16-alpine"
                " -> ghcr.io/acme/web:17-alpine (major)",
                "- tool (beta): ghcr.io/acme/tool:v3.3.5"
                " -> ghcr.io/acme/tool:v3.4.0 (minor)",
            ]
            for line in expected:
                if line not in body:
                    raise SystemExit(f"missing report line {line!r} in {body!r}")
            if "drift:2.0.0 tag moved" in body:
                raise SystemExit(f"digest finding was not superseded: {body!r}")
            for unwanted in ("- pg (", "built", "ignored"):
                if unwanted in body:
                    raise SystemExit(f"skipped service leaked into the report: {body!r}")
            if "$" in body:
                raise SystemExit(f"unresolved variable leaked into the report: {body!r}")

            state = json.loads(case.state.read_text())
            if state["stacks_scanned"] != ["alpha", "beta"]:
                raise SystemExit(f"wrong stacks scanned: {state['stacks_scanned']!r}")
            if state["errors"]:
                raise SystemExit(f"unexpected errors: {state['errors']!r}")
            kinds = sorted(item["kind"] for item in state["findings"])
            if kinds != ["digest", "major", "minor", "patch", "patch", "patch"]:
                raise SystemExit(f"wrong findings in state: {state['findings']!r}")

            # -- majors dropped entirely -----------------------------------
            case.write_config(ignore_images=["ghcr.io/acme/ignored"], include_major=False)
            result = case.run()
            if result.returncode != 0:
                raise SystemExit(f"no-major run failed: {result.stderr}")
            messages = case.notifications()
            if len(messages) != 1:
                raise SystemExit(f"expected one notification, got {messages!r}")
            args = messages[0]
            if not args[-2].endswith(": 5 available"):
                raise SystemExit(f"major findings were counted: {args[-2]!r}")
            if "major:" in args[-1] or "17-alpine" in args[-1]:
                raise SystemExit(f"major findings were reported: {args[-1]!r}")

            # -- --no-notify still writes the state -------------------------
            case.write_config(ignore_images=["ghcr.io/acme/ignored"])
            result = case.run("--no-notify")
            if result.returncode != 0:
                raise SystemExit(f"--no-notify run failed: {result.stderr}")
            if case.notifications():
                raise SystemExit("--no-notify sent a notification")
            if not case.state.exists():
                raise SystemExit("--no-notify did not write the state file")

            # -- --dry-run prints and writes nothing ------------------------
            case.state.unlink()
            result = case.run("--dry-run")
            if result.returncode != 0:
                raise SystemExit(f"--dry-run run failed: {result.stderr}")
            if case.notifications():
                raise SystemExit("--dry-run sent a notification")
            if case.state.exists():
                raise SystemExit("--dry-run wrote the state file")
            if "docker updates " not in result.stdout or "major:" not in result.stdout:
                raise SystemExit(f"--dry-run printed no report: {result.stdout!r}")

            # -- release_sources: GitHub releases instead of registry tags --
            rel = Case(root / "releases", registry_url)
            rel.stack("relstack", {"app": {"image": "ghcr.io/acme/relapp:v3.3.5"}})
            rel.write_config(release_sources={"ghcr.io/acme/relapp": "acme/relapp"})
            result = rel.run()
            if result.returncode != 0:
                raise SystemExit(f"release source run failed: {result.stderr}")
            messages = rel.notifications()
            if len(messages) != 1:
                raise SystemExit(f"expected one release notification, got {messages!r}")
            body = messages[0][-1]
            expected = (
                "- app (relstack): ghcr.io/acme/relapp:v3.3.5"
                " -> ghcr.io/acme/relapp:v3.4.0 (minor)"
            )
            if expected not in body:
                raise SystemExit(f"missing release line {expected!r} in {body!r}")
            if "v3.6.0" in body:
                raise SystemExit(f"prerelease was reported: {body!r}")

            # -- clean run sends nothing ------------------------------------
            clean = Case(root / "clean", registry_url)
            clean.stack("only", {"current": {"image": "ghcr.io/acme/current:1.2.3"}})
            result = clean.run()
            if result.returncode != 0:
                raise SystemExit(f"clean run failed: {result.stderr}")
            if clean.notifications():
                raise SystemExit("clean run sent a notification")
            state = json.loads(clean.state.read_text())
            if state["findings"] or state["errors"]:
                raise SystemExit(f"clean state is not clean: {state!r}")

            # -- notify_when_current sends the sign of life -----------------
            clean.write_config(notify_when_current=True)
            result = clean.run()
            if result.returncode != 0:
                raise SystemExit(f"current run failed: {result.stderr}")
            messages = clean.notifications()
            if len(messages) != 1 or "all pinned images current" not in messages[0][-1]:
                raise SystemExit(f"missing sign-of-life notification: {messages!r}")
            if not messages[0][-2].endswith(": 0 available"):
                raise SystemExit(f"wrong sign-of-life subject: {messages[0][-2]!r}")

            # -- a broken stack is an error, not a failed run ---------------
            broken = Case(root / "broken", registry_url)
            broken.stack("ok", {"app": {"image": "ghcr.io/acme/current:1.2.3"}})
            (broken.stacks / "bad").mkdir()
            (broken.stacks / "bad" / "compose.yaml").write_text("services: {}\n")
            result = broken.run()
            if result.returncode != 0:
                raise SystemExit(f"broken stack failed the run: {result.stderr}")
            state = json.loads(broken.state.read_text())
            if not state["errors"] or "bad" not in state["errors"][0]:
                raise SystemExit(f"broken stack was not recorded: {state!r}")
            if state["stacks_scanned"] != ["ok"]:
                raise SystemExit(f"broken stack was counted as scanned: {state!r}")

            # -- missing stacks directory is a configuration error ----------
            broken.write_config(stacks_dir=str(root / "does-not-exist"))
            result = broken.run()
            if result.returncode != 2 or "stacks directory not found" not in result.stderr:
                raise SystemExit(
                    f"missing stacks dir: rc={result.returncode} stderr={result.stderr!r}"
                )

            # -- transient 429 is retried and the check still succeeds ------
            transient = Case(root / "transient", registry_url)
            transient.stack(
                "retry",
                {
                    "app": {
                        "image": "ghcr.io/acme/flaky:2.0.0@"
                        + digest_for("acme/flaky", "2.0.0")
                    }
                },
            )
            result = transient.run()
            if result.returncode != 0:
                raise SystemExit(f"transient retry run failed: {result.stderr}")
            state = json.loads(transient.state.read_text())
            if state["errors"]:
                raise SystemExit(f"transient 429 was not retried: {state['errors']!r}")
            if state["findings"]:
                raise SystemExit(f"transient run invented findings: {state['findings']!r}")
            hits = manifest_hits.get(("acme/flaky", "2.0.0"), 0)
            if hits != 3:
                raise SystemExit(f"expected 3 manifest attempts, saw {hits}")

            # -- a persistent 429 stays non-fatal and lands in errors ------
            persistent = Case(root / "persistent", registry_url)
            persistent.stack(
                "stuck",
                {
                    "app": {
                        "image": "ghcr.io/acme/stuck:2.0.0@sha256:"
                        + hashlib.sha256(b"never").hexdigest()
                    }
                },
            )
            # Nothing is outdated here, so the sign-of-life flag is what makes
            # the failure line reach the notification body at all.
            persistent.write_config(notify_when_current=True)
            result = persistent.run()
            if result.returncode != 0:
                raise SystemExit(f"persistent 429 failed the run: {result.stderr}")
            state = json.loads(persistent.state.read_text())
            if not any(
                "HTTP 429 for " in error
                and "/v2/acme/stuck/manifests/2.0.0" in error
                for error in state["errors"]
            ):
                raise SystemExit(f"persistent 429 was not recorded: {state['errors']!r}")
            hits = manifest_hits.get(("acme/stuck", "2.0.0"), 0)
            if hits != 3:
                raise SystemExit(f"expected 3 manifest attempts, saw {hits}")
            messages = persistent.notifications()
            if len(messages) != 1:
                raise SystemExit(f"expected one failure notification, got {messages!r}")
            if not messages[0][-1].endswith("1 check(s) failed; see the state file"):
                raise SystemExit(f"failure line missing from body: {messages[0][-1]!r}")
    finally:
        server.shutdown()
        server.server_close()

    print("image updates tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
