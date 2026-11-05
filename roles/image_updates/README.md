# image_updates

Weekly read-only report of Docker images that have a newer tag at the
registry. The deployed image references come from `docker compose config`
on each stack, so `${VERSION}` placeholders in a Compose file are resolved
by Compose itself and no `.env` value is read or printed by the reporter.

The role installs a script and a config file; it does not pull, restart or
edit anything. The only writes are the JSON state file and one
notification, and the schedule belongs to `scheduled_jobs`.

## What it does

1. Installs `/usr/local/bin/hsp-image-updates` and
   `/etc/hsp/image-updates.json`.
2. Discovers every stack directory under `image_updates_stacks_dir` that
   contains a Compose file, then applies the include/exclude lists.
3. Runs `docker compose --project-directory <dir> -f <file> config
   --format json` per stack with `image_updates_compose_timeout`. A failing
   stack is recorded under `errors` and the rest continue.
4. Skips services with a `build` key (locally built images), an empty
   `image`, or a reference listed in `image_updates_ignore_images`.
5. Asks the registry for the tag list and, for digest-pinned images, the
   digest the tag currently resolves to. Authentication is anonymous:
   a `401` challenge is answered by fetching a Bearer token from the
   realm the registry advertises. Docker Hub and GHCR work without
   credentials for public images. An image listed in
   `image_updates_release_sources` is compared against its GitHub releases
   instead, because some projects publish an impractical number of tags
   (Immich's machine-learning image has more than 200,000).
6. Reports two kinds of finding:
   - **semver tags** - `[v]MAJOR[.MINOR[.PATCH]][-suffix]`, compared only
     within the same suffix and the same number of numeric components, so
     `16-alpine` competes with `17-alpine` and `2.11.7` with `2.11.8`.
     Pre-release/rc tags are ignored. The highest candidate is classified
     `patch`, `minor` or `major`.
   - **digest drift** - when the image is pinned with `@sha256:<digest>`
     and the tag now resolves to a different digest, reported as
     `tag moved (digest)`. Non-semver tags such as
     `14-vectorchord0.4.3-pg17` only get this check.
7. Sends one digest through `hsp-notify` with subject
   `docker updates <hostname>: N available` and writes the state file
   atomically. Nothing found and `image_updates_notify_when_current`
   false means no notification at all; the state file is still written.

Registry failures are not fatal: they land in `errors` in the state file
and the run exits 0. A missing config or stacks directory exits 2, and a
broken run or a failed notification exits non-zero, so the scheduled job's
`OnFailure` still fires for a reporter that stopped working.

## Variables

| Variable | Default | Description |
|---|---|---|
| `image_updates_enabled` | `false` | Install the reporter and its config |
| `image_updates_bin` | `/usr/local/bin/hsp-image-updates` | Installed script |
| `image_updates_config` | `/etc/hsp/image-updates.json` | Rendered configuration |
| `image_updates_state_file` | `/var/lib/hsp/image-updates.json` | Last run as JSON |
| `image_updates_stacks_dir` | `/opt/stacks` | Where the Compose stacks live |
| `image_updates_include_stacks` | `[]` | Only these stack directory names; empty means all |
| `image_updates_exclude_stacks` | `[]` | Stack directory names to skip |
| `image_updates_ignore_images` | `[]` | Exact image references or repo names to skip |
| `image_updates_release_sources` | `{}` | Image name -> GitHub project, for repos whose tag list is too large |
| `image_updates_include_major` | `true` | Keep major jumps in a separate `major:` section; `false` drops them |
| `image_updates_notify_when_current` | `false` | Send a digest even when nothing is outdated |
| `image_updates_notify_bin` | `hsp-notify` | Notification helper |
| `image_updates_notify_priority` | `low` | ntfy priority |
| `image_updates_notify_tags` | `update_report,docker` | ntfy tags |
| `image_updates_schedule` | `Sun *-*-* 21:00:00` | `OnCalendar` for the scheduled job; the role creates no timer |
| `image_updates_registry_timeout` | `20` | Seconds per registry request |
| `image_updates_compose_timeout` | `30` | Seconds per `docker compose config` |

The rendered JSON uses the variable name without the `image_updates_`
prefix (`stacks_dir`, `ignore_images`, `notify_bin`, ...), and the script
falls back to the same values when a key is absent.

The digest cadence is not baked into the script: it is the `schedule` of the
`scheduled_jobs` entry. Reference `image_updates_schedule` there so the
interval lives with the rest of the role settings:

```yaml
scheduled_jobs_host:
  - name: image-updates
    command: /usr/local/bin/hsp-image-updates
    schedule: "{{ image_updates_schedule }}"
    description: "Weekly Docker image update digest"
    notify_on_failure: true
```

Define `image_updates_schedule` in `host_vars` (not only in the role
defaults), because `scheduled_jobs` renders its units in an earlier play
than this role runs.

## Example

```yaml
image_updates_enabled: true
image_updates_include_major: true
image_updates_ignore_images:
  - ghcr.io/example/legacy-app
image_updates_exclude_stacks:
  - scratch
image_updates_release_sources:
  "ghcr.io/immich-app/immich-server": immich-app/immich
  "ghcr.io/immich-app/immich-machine-learning": immich-app/immich
```

The GitHub releases API is unauthenticated, which allows 60 requests per
hour; a weekly run uses one request per mapped image. Draft and pre-release
releases are ignored.

Run it by hand:

```bash
sudo /usr/local/bin/hsp-image-updates --dry-run
cat /var/lib/hsp/image-updates.json
```

`--dry-run` prints the report, sends nothing and writes no state.
`--no-notify` writes the state but sends nothing. `--stacks-dir PATH`
overrides the configured directory.

## Scheduling

```yaml
scheduled_jobs_common:
  - name: image-updates
    command: /usr/local/bin/hsp-image-updates
    schedule: "Mon *-*-* 06:00:00"
    description: "Weekly Docker image update report"
    notify_on_failure: true
```

The job needs the Docker CLI and read access to the stack directories; it
does not need the Docker daemon, because `docker compose config` only
reads files.

## Testing

```bash
make test-image-updates
```

The test runs the script against a fake `docker`, a fake notify binary and
a local HTTP registry, so it needs no daemon and no network.

> [!NOTE]
> `HSP_IMAGE_UPDATES_TEST_REGISTRY` rewrites every registry URL to the
> given base (for example `http://127.0.0.1:5000`). It exists only for the
> test suite and must never be set on a host.

## Limitations

- Only tags with the same suffix and numeric component count are compared;
  a stack pinned to `16-alpine` is not told about the plain `17` tag, and a
  variant added later (for example `17-alpine3.21`) is not a candidate
  unless the reference is changed by hand.
- A repository with more than 5000 tags is truncated; the highest version
  may fall outside the window in extreme cases.
- Anonymous registry access only. A private image shows up under `errors`
  in the state file.
