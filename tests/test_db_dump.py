#!/usr/bin/env python3
"""Behaviour checks for roles/db_dump/files/hsp-db-dump.

The tests keep everything offline: PostgreSQL and MySQL run through a fake
`docker` that writes a marker to stdout, and SQLite uses real temporary
databases. They cover paths, globs, retention, freshness, failures, config
validation and dry runs.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "roles" / "db_dump" / "files" / "hsp-db-dump"

FAKE_DOCKER = """#!/bin/sh
printf '%s\\n' "$*" >> "$DOCKER_LOG"
if [ "${DOCKER_FAIL:-0}" = "1" ]; then
    echo "fake docker failure" >&2
    exit 2
fi
printf 'FAKE-DUMP:%s\\n' "$*"
"""


def write_config(root: Path, data: dict) -> Path:
    data = dict(data)
    data.setdefault("lock_file", str(root / "lock"))
    path = root / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def run(
    root: Path, config: Path, *args: str, docker_fail: bool = False
) -> subprocess.CompletedProcess[str]:
    bin_dir = root / "bin"
    bin_dir.mkdir(exist_ok=True)
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    log = root / "docker.log"
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["DOCKER_LOG"] = str(log)
    env["DOCKER_FAIL"] = "1" if docker_fail else "0"
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--config", str(config), *args],
        env=env,
        capture_output=True,
        text=True,
    )


def make_sqlite(path: Path, value: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (v TEXT)")
    con.execute("INSERT INTO t VALUES (?)", (value,))
    con.commit()
    con.close()


def assert_ok(result: subprocess.CompletedProcess[str]) -> None:
    if result.returncode != 0:
        raise SystemExit(
            f"expected success, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


def assert_fail(result: subprocess.CompletedProcess[str], code: int = 1) -> None:
    if result.returncode != code:
        raise SystemExit(
            f"expected exit {code}, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


def test_sqlite_path_and_retention() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "src" / "app.db"
        make_sqlite(source)
        out = root / "backups"
        config = write_config(
            root,
            {
                "sqlite": [
                    {
                        "name": "app",
                        "path": str(source),
                        "output": str(out),
                        "keep": 2,
                    }
                ]
            },
        )
        assert_ok(run(root, config))
        dumps = sorted(out.glob("app-*.sqlite3"))
        if len(dumps) != 1:
            raise SystemExit(f"expected one dump, got {dumps}")
        dump = dumps[0]
        if stat.S_IMODE(dump.stat().st_mode) != 0o600:
            raise SystemExit(f"dump mode is not 0600: {oct(dump.stat().st_mode)}")
        con = sqlite3.connect(dump)
        value = con.execute("SELECT v FROM t").fetchone()
        con.close()
        if value != ("x",):
            raise SystemExit(f"dump content is wrong: {value!r}")

        for old in ("app-2020-01-01_00-00-00.sqlite3", "app-2020-01-02_00-00-00.sqlite3"):
            path = out / old
            path.write_text("old", encoding="utf-8")
            os.utime(path, (time.time() - 86400, time.time() - 86400))
        assert_ok(run(root, config))
        dumps = sorted(out.glob("app-*.sqlite3"))
        if len(dumps) != 2:
            raise SystemExit(f"retention did not keep 2 files: {dumps}")
        if any(path.name.startswith("app-2020-01-01") for path in dumps):
            raise SystemExit(f"oldest dump was not pruned: {dumps}")


def test_sqlite_glob_labels() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for label in ("a", "b"):
            make_sqlite(root / "db" / label / "up2k.db", label)
        out = root / "backups"
        config = write_config(
            root,
            {
                "sqlite": [
                    {
                        "name": "copyparty",
                        "glob": str(root / "db" / "*" / "up2k.db"),
                        "label_from": "parent",
                        "output": str(out),
                        "keep": 5,
                    }
                ]
            },
        )
        assert_ok(run(root, config))
        labels = sorted(path.name.split("-")[1] for path in out.glob("copyparty-*.sqlite3"))
        if labels != ["a", "b"]:
            raise SystemExit(f"glob labels are wrong: {labels}")


def test_postgres_custom() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        out = root / "backups"
        config = write_config(
            root,
            {
                "postgres": [
                    {
                        "name": "joplin",
                        "container": "joplin-db",
                        "user": "joplin",
                        "database": "joplin",
                        "password_env": "POSTGRES_PASSWORD",
                        "output": str(out),
                        "retention": {"daily": 2, "weekly": 0, "monthly": 0},
                    }
                ]
            },
        )
        assert_ok(run(root, config))
        dumps = sorted((out / "daily").glob("joplin_daily_*.dump"))
        if len(dumps) != 1:
            raise SystemExit(f"expected one PostgreSQL dump, got {dumps}")
        if not dumps[0].read_text(encoding="utf-8").startswith("FAKE-DUMP:"):
            raise SystemExit("PostgreSQL dump content is wrong")
        log = (root / "docker.log").read_text(encoding="utf-8")
        for needle in ("pg_dump", "-U", "joplin", "-d", "-Fc", 'PGPASSWORD="$POSTGRES_PASSWORD"'):
            if needle not in log:
                raise SystemExit(f"docker command is missing {needle!r}: {log}")
        if " -T " in log:
            raise SystemExit(f"docker exec does not support -T: {log}")
        if (out / "weekly").exists() or (out / "monthly").exists():
            raise SystemExit("disabled retention periods were created")


def test_postgres_dumpall() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        out = root / "backups"
        config = write_config(
            root,
            {
                "postgres": [
                    {
                        "name": "all",
                        "container": "postgres",
                        "user": "postgres",
                        "format": "dumpall",
                        "output": str(out),
                        "retention": {"daily": 1, "weekly": 0, "monthly": 0},
                    }
                ]
            },
        )
        assert_ok(run(root, config))
        dumps = sorted((out / "daily").glob("all_daily_*.sql"))
        if len(dumps) != 1:
            raise SystemExit(f"expected one dumpall dump, got {dumps}")
        log = (root / "docker.log").read_text(encoding="utf-8")
        if "pg_dumpall" not in log or " -d " in log:
            raise SystemExit(f"dumpall command is wrong: {log}")


def test_mysql() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        out = root / "backups"
        config = write_config(
            root,
            {
                "mysql": [
                    {
                        "name": "app",
                        "container": "app-db",
                        "user": "app",
                        "database": "app",
                        "password_env": "MYSQL_PASSWORD",
                        "output": str(out),
                        "retention": {"daily": 1, "weekly": 0, "monthly": 0},
                    }
                ]
            },
        )
        assert_ok(run(root, config))
        dumps = sorted((out / "daily").glob("app_daily_*.sql"))
        if len(dumps) != 1:
            raise SystemExit(f"expected one MySQL dump, got {dumps}")
        log = (root / "docker.log").read_text(encoding="utf-8")
        for needle in (
            "mysqldump",
            "--single-transaction",
            "--quick",
            "--routines",
            "--events",
            "--triggers",
            "-u",
            'MYSQL_PWD="$MYSQL_PASSWORD"',
        ):
            if needle not in log:
                raise SystemExit(f"docker command is missing {needle!r}: {log}")
        if " -T " in log:
            raise SystemExit(f"docker exec does not support -T: {log}")


def test_freshness() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dump = root / "dumps" / "immich-1.sql.gz"
        dump.parent.mkdir()
        dump.write_text("dump", encoding="utf-8")
        config = write_config(
            root,
            {
                "freshness": [
                    {
                        "name": "immich",
                        "glob": str(root / "dumps" / "immich-*.sql.gz"),
                        "max_age_hours": 1,
                    }
                ]
            },
        )
        assert_ok(run(root, config))
        old = time.time() - 2 * 3600
        os.utime(dump, (old, old))
        result = run(root, config)
        assert_fail(result)
        if "old" not in result.stderr:
            raise SystemExit(f"freshness failure is unclear: {result.stderr}")


def test_missing_sqlite() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        config = write_config(
            root,
            {
                "sqlite": [
                    {
                        "name": "missing",
                        "path": str(root / "does-not-exist.db"),
                        "output": str(root / "backups"),
                    }
                ]
            },
        )
        result = run(root, config)
        assert_fail(result)
        if "not found" not in result.stderr:
            raise SystemExit(f"missing SQLite failure is unclear: {result.stderr}")


def test_failing_docker_writes_nothing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        out = root / "backups"
        config = write_config(
            root,
            {
                "postgres": [
                    {
                        "name": "joplin",
                        "container": "joplin-db",
                        "user": "joplin",
                        "database": "joplin",
                        "output": str(out),
                        "retention": {"daily": 1, "weekly": 0, "monthly": 0},
                    }
                ]
            },
        )
        result = run(root, config, docker_fail=True)
        assert_fail(result)
        if list(out.rglob("*.dump")):
            raise SystemExit("a failed dump left a file behind")
        if "fake docker failure" not in result.stderr:
            raise SystemExit(f"docker failure is unclear: {result.stderr}")


def test_duplicate_names() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        config = write_config(
            root,
            {
                "postgres": [
                    {
                        "name": "same",
                        "container": "one",
                        "user": "u",
                        "database": "d",
                        "output": str(root / "one"),
                    }
                ],
                "sqlite": [
                    {
                        "name": "same",
                        "path": str(root / "x.db"),
                        "output": str(root / "two"),
                    }
                ],
            },
        )
        result = run(root, config)
        assert_fail(result, code=2)
        if "duplicate" not in result.stderr:
            raise SystemExit(f"duplicate-name failure is unclear: {result.stderr}")


def test_dry_run_writes_nothing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "src" / "app.db"
        make_sqlite(source)
        out = root / "backups"
        config = write_config(
            root,
            {
                "sqlite": [
                    {
                        "name": "app",
                        "path": str(source),
                        "output": str(out),
                    }
                ]
            },
        )
        result = run(root, config, "--dry-run")
        assert_ok(result)
        if out.exists() and list(out.rglob("*.sqlite3")):
            raise SystemExit("dry run wrote a dump")
        if "would" not in result.stdout:
            raise SystemExit(f"dry run output is unclear: {result.stdout}")


def main() -> int:
    test_sqlite_path_and_retention()
    test_sqlite_glob_labels()
    test_postgres_custom()
    test_postgres_dumpall()
    test_mysql()
    test_freshness()
    test_missing_sqlite()
    test_failing_docker_writes_nothing()
    test_duplicate_names()
    test_dry_run_writes_nothing()
    print("db_dump tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
