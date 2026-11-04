# docker_prune

Installs `hsp-docker-prune`, the cleanup command that `compose_deploy` runs
after all stacks are up. It can also be scheduled with `scheduled_jobs`, but
the deploy hook is the default because that is when replaced images lose
their last container reference.

## What it does

- `docker image prune -a -f`: removes every image not used by a container.
  Images of running or stopped stacks stay while a container references
  them; a replaced version has no container left and is removed.
- `docker builder prune -f --all`: removes the BuildKit cache (optional).

A rollback pulls the old tag or digest again. Volumes, containers and
networks are never touched.

## What it never does

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
| `HSP_DOCKER_PRUNE_BUILD_CACHE` | `1` | Set to `0` to skip the build-cache prune, for example on a host that builds images regularly |

## Usage

```yaml
# host_vars or group_vars
compose_deploy_prune: true
```

The `docker_prune` role must run before `compose_deploy` so the command
exists. For a timer instead of the deploy hook:

```yaml
scheduled_jobs_common:
  - name: docker-prune
    command: /usr/local/bin/hsp-docker-prune
    schedule: "*-*-* 04:30:00"
    randomized_delay: "30m"
    description: "Docker image and build-cache prune"
    notify_on_failure: true
```
