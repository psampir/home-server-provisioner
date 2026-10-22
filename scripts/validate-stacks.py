#!/usr/bin/env python3
"""Validate container image references in Compose stacks.

Checks every ``image:`` entry under ``configs/<ENV>/stacks/**`` for:

* malformed ``@sha256:`` digests (must be 64 hex characters) - always an
  error;
* unpinned tags - a warning by default, an error with ``--strict-tags``;
* digest existence in the registry - only with ``--check-registry``.

Tag warnings can be allowlisted per environment in
``configs/<ENV>/stacks/validate-allowlist.txt`` (one pattern per line,
``#`` comments) or with ``--allow-tags``. A pattern matches when it is a
case-insensitive substring of the image repository, or a glob matched
against the full reference and the repository.

Usage:
    scripts/validate-stacks.py --env prod
    scripts/validate-stacks.py --env prod --check-registry
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only without PyYAML
    print(
        "validate-stacks: PyYAML is required (install ansible or python3-pyyaml)",
        file=sys.stderr,
    )
    raise SystemExit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_NAMES = ("docker-compose.yml", "compose.yml", "compose.yaml")
DIGEST_RE = re.compile(r"^sha256:([0-9a-fA-F]{64})$")
ALLOWLIST_NAME = "validate-allowlist.txt"


class Finding:
    """One validation result for one image reference."""

    def __init__(self, path: Path, level: str, message: str) -> None:
        self.path = path
        self.level = level
        self.message = message


def display(path: Path) -> str:
    """Render a path relative to the repository root when possible."""
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def split_tag(reference: str) -> tuple[str, str | None]:
    """Split a repository:tag reference (no digest) into repo and tag."""
    slash = reference.rfind("/")
    colon = reference.rfind(":")
    if colon > slash:
        return reference[:colon], reference[colon + 1 :]
    return reference, None


def load_allowlist(path: Path) -> list[str]:
    if not path.is_file():
        return []
    patterns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        patterns.append(entry)
    return patterns


def is_allowlisted(repo: str, reference: str, patterns: list[str]) -> bool:
    lowered_repo = repo.lower()
    lowered_ref = reference.lower()
    for pattern in patterns:
        lowered = pattern.lower()
        if lowered in lowered_repo:
            return True
        if fnmatch.fnmatch(lowered_ref, lowered):
            return True
        if fnmatch.fnmatch(lowered_repo, lowered):
            return True
    return False


def iter_image_entries(path: Path):
    """Yield (service, image) pairs from a Compose file."""
    try:
        documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot parse {display(path)}: {exc}") from exc

    for document in documents:
        if not isinstance(document, dict):
            continue
        services = document.get("services")
        if not isinstance(services, dict):
            continue
        for service_name, service in services.items():
            if not isinstance(service, dict):
                continue
            if "image" in service:
                yield str(service_name), service["image"]


def discover_compose_files(stacks_dir: Path) -> list[Path]:
    files = []
    for name in COMPOSE_NAMES:
        files.extend(stacks_dir.rglob(name))
    return sorted(set(files))


def parse_image(image: str) -> tuple[str, str | None, str | None, str | None]:
    """Return (repo, tag, digest, error) for one image reference.

    ``repo`` never includes the tag. ``error`` is set for a malformed
    digest; the caller turns it into a failure.
    """
    reference = image.strip()
    if "@" in reference:
        if reference.count("@") > 1:
            return reference, None, None, "contains more than one @"
        repo_with_tag, digest = reference.rsplit("@", 1)
        if not digest:
            return repo_with_tag, None, None, "empty digest"
        if not digest.startswith("sha256:"):
            return repo_with_tag, None, digest, "unsupported digest algorithm (expected sha256)"
        if not DIGEST_RE.match(digest):
            return repo_with_tag, None, digest, "sha256 digest must be 64 hex characters"
        repo, tag = split_tag(repo_with_tag)
        return repo, tag, digest, None

    repo, tag = split_tag(reference)
    return repo, tag, None, None


def detect_registry_tool(requested: str) -> str | None:
    if requested != "auto":
        return requested if shutil.which(requested) else None
    for tool in ("docker", "skopeo", "crane"):
        if shutil.which(tool):
            return tool
    return None


def registry_command(tool: str, reference: str) -> list[str]:
    if tool == "docker":
        return ["docker", "manifest", "inspect", reference]
    if tool == "skopeo":
        return ["skopeo", "inspect", "--raw", f"docker://{reference}"]
    return ["crane", "manifest", reference]


def check_registry(tool: str, reference: str, timeout: int) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            registry_command(tool, reference),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)

    if result.returncode == 0:
        return True, ""
    detail = (result.stderr or result.stdout).strip().splitlines()
    first = detail[0] if detail else f"exit code {result.returncode}"
    if len(first) > 300:
        first = first[:297] + "..."
    return False, first


def validate(args: argparse.Namespace) -> int:
    stacks_dir = Path(args.configs_root) / args.env / "stacks"
    if not stacks_dir.is_dir():
        print(f"validate-stacks: {display(stacks_dir)} not found", file=sys.stderr)
        return 2

    compose_files = discover_compose_files(stacks_dir)
    if not compose_files:
        print(
            f"validate-stacks: no Compose files under {display(stacks_dir)}",
            file=sys.stderr,
        )
        return 2

    allowlist_path = stacks_dir / ALLOWLIST_NAME
    patterns = load_allowlist(allowlist_path) + args.allow_tags
    findings: list[Finding] = []

    registry_tool = None
    if args.check_registry:
        registry_tool = detect_registry_tool(args.registry_tool)
        if registry_tool is None:
            print(
                "validate-stacks: no registry tool found; install the docker CLI, "
                "skopeo, or crane, or pass --registry-tool",
                file=sys.stderr,
            )
            return 2

    registry_cache: dict[str, tuple[bool, str]] = {}
    pinned = 0
    unpinned = 0

    for path in compose_files:
        try:
            entries = list(iter_image_entries(path))
        except ValueError as exc:
            findings.append(Finding(path, "error", str(exc)))
            continue

        for service, raw_image in entries:
            if not isinstance(raw_image, str) or not raw_image.strip():
                findings.append(
                    Finding(
                        path,
                        "error",
                        f"service {service}: image is not a non-empty string",
                    )
                )
                continue

            image = raw_image.strip()
            repo, tag, digest, error = parse_image(image)
            if error is not None:
                findings.append(
                    Finding(
                        path,
                        "error",
                        f"service {service}: image {image!r}: {error}",
                    )
                )
                continue

            if digest is None:
                unpinned += 1
                label = f"{repo}:{tag}" if tag else repo
                if is_allowlisted(repo, image, patterns):
                    findings.append(
                        Finding(
                            path,
                            "info",
                            f"service {service}: {label} is not pinned to a digest (allowlisted)",
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            path,
                            "warning",
                            f"service {service}: {label} is not pinned to a digest",
                        )
                    )
                continue

            pinned += 1
            if registry_tool is None:
                continue

            check_ref = f"{repo}@{digest}"
            if "$" in check_ref:
                findings.append(
                    Finding(
                        path,
                        "error",
                        f"service {service}: cannot verify a digest for a reference "
                        "containing variable substitution",
                    )
                )
                continue

            if check_ref not in registry_cache:
                registry_cache[check_ref] = check_registry(
                    registry_tool, check_ref, args.registry_timeout
                )
            ok, detail = registry_cache[check_ref]
            if not ok:
                findings.append(
                    Finding(
                        path,
                        "error",
                        f"service {service}: registry check failed for digest "
                        f"{digest} ({detail})",
                    )
                )

    for finding in findings:
        prefix = {
            "error": "ERROR",
            "warning": "WARN ",
            "info": "INFO ",
        }[finding.level]
        print(f"{prefix} {display(finding.path)}: {finding.message}")

    errors = sum(1 for item in findings if item.level == "error")
    warnings = sum(1 for item in findings if item.level == "warning")
    reported_warnings = warnings
    if args.strict_tags:
        errors += warnings
        reported_warnings = 0

    scope = f"{len(compose_files)} file(s), {pinned} pinned, {unpinned} unpinned"
    if registry_tool is not None:
        scope += f", registry checked with {registry_tool}"
    strict = " (strict tags)" if args.strict_tags else ""
    print(
        f"validate-stacks: {scope}; {errors} error(s){strict}, "
        f"{reported_warnings} warning(s)"
    )

    return 1 if errors else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate image references in Compose stacks."
    )
    parser.add_argument(
        "--env",
        default="prod",
        help="environment under configs/ (default: prod)",
    )
    parser.add_argument(
        "--configs-root",
        default=str(REPO_ROOT / "configs"),
        help="root directory containing per-environment config trees",
    )
    parser.add_argument(
        "--check-registry",
        action="store_true",
        help="verify every pinned digest against its registry (needs network)",
    )
    parser.add_argument(
        "--registry-tool",
        default="auto",
        choices=("auto", "docker", "skopeo", "crane"),
        help="registry client to use with --check-registry (default: auto)",
    )
    parser.add_argument(
        "--registry-timeout",
        type=int,
        default=60,
        help="seconds per registry request (default: 60)",
    )
    parser.add_argument(
        "--allow-tags",
        action="append",
        default=[],
        metavar="PATTERN[,PATTERN]",
        help="allowlist pattern for unpinned tags; repeatable",
    )
    parser.add_argument(
        "--strict-tags",
        action="store_true",
        help="treat unpinned tags as errors instead of warnings",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    expanded: list[str] = []
    for value in args.allow_tags:
        expanded.extend(
            item.strip() for item in value.split(",") if item.strip()
        )
    args.allow_tags = expanded

    return validate(args)


if __name__ == "__main__":
    raise SystemExit(main())
