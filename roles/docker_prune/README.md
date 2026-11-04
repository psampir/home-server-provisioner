# docker_prune

Installs `hsp-docker-prune`, the command body for a scheduled Docker cleanup.
The schedule and the notification live in `scheduled_jobs`, so this role only
ships the script and keeps the same pattern as `hsp-disk-check`.

## What it does

- `docker image prune -f --filter until=<retention>`: dangling images only.
- `docker builder prune -f --all`: the whole BuildKit cache (optional). The
  age filter does not cover internal/frontend records, and the cache is
  regenerable, so it is pruned in full.

Defaults: image retention `48h` (two days), build cache enabled.

## What it never does

- `docker image prune -a`, so tagged images of stopped stacks and
  digest-pinned rollback images survive while a container references them.
- `docker volume prune` or `docker system prune`, because volumes can hold
  application data and stopped containers may be intentional.
- `docker container prune` or network pruning.

## Variables

| Variable | Default | Description |
|---|---|---|
| `docker_prune_bin` | `/usr/local/bin/hsp-docker-prune` | Installed path |

## Environment

| Variable | Default | Description |
|---|---|---|
| `HSP_DOCKER_PRUNE_UNTIL` | `48h` | Age filter for the image prune |
| `HSP_DOCKER_PRUNE_BUILD_CACHE` | `1` | Set to `0` to skip the build-cache prune, for example on a host that builds images regularly |

## Scheduling

```yaml
scheduled_jobs_common:
  - name: docker-prune
    command: /usr/local/bin/hsp-docker-prune
    schedule: "*-*-* 04:30:00"
    randomized_delay: "30m"
    description: "Daily Docker image and build-cache prune"
    notify_on_failure: true
```

The first run also reclaims cache left by earlier local builds. Images that
are still referenced by a container, including a stopped stack, are kept.
