# RabbitMQ 3.7 → 3.13 upgrade

The compose default moved from `rabbitmq:3.7-alpine` to `rabbitmq:3.13-alpine`.
**This is not an in-place upgrade** — the broker's data directory has to be
recreated. Read this before deploying.

## Why 3.13 and not 4.x

4.x was tried first and does not work with this application.

RabbitMQ 4 removed **transient non-exclusive queues**. That is exactly what
Celery declares for its control (pidbox) queues, its event queues, and the
`rpc://` result backend this project uses (`CELERY_RESULT_BACKEND = "rpc://"`).
Against a 4.3 broker the worker dies on startup and keeps restarting:

```
amqp.exceptions.InternalError: Queue.declare: (541) INTERNAL_ERROR -
  Feature `transient_nonexcl_queues` is deprecated.
```

and beat cannot dispatch anything:

```
celery.beat.SchedulingError: Couldn't apply scheduled task
  get_sustaining_members: channel disconnected
```

The durable task queues (`celery`, `qt6`) are fine — it is the control, event
and result plumbing that breaks. So a smoke test that only publishes to a
durable queue will pass while the application is completely broken. Test with
`celery inspect ping` and a real task, not with a hand-rolled durable publish.

3.13 is the last line that still permits these queues. Getting to 4.x needs one
of:

- `deprecated_features.permit.transient_nonexcl_queues = true` in a mounted
  `rabbitmq.conf` — works, but the feature is scheduled for removal outright, so
  it only buys time; or
- Celery/kombu declaring durable queues for control, events and results, which
  is an upstream change, not a configuration one.

Either way it is its own piece of work, not a tag bump. 3.13 gets us off a
release that has been end-of-life since 2020.

## Why the data directory has to be recreated

RabbitMQ supports upgrading between adjacent minor versions. 3.7 → 3.13 is six
minors, and 3.7 predates the feature-flags subsystem entirely, so a 3.13 node
will not start cleanly against a directory written by 3.7.

## Why that is safe

The broker holds nothing worth preserving. Checked against the running
instance (3.7.28) rather than assumed:

```
name                                       messages  durable
celery                                     0         true
qt6                                        0         true
celery@uwsgi.celery.pidbox                 0         false
celeryev.<uuid>                            0         false
<uuid>                                     3         false
```

- The only **durable** queues, `celery` and `qt6`, were **empty**.
- Everything else is a transient Celery control/event/result queue, short-lived
  by design.
- Celery re-declares its queues and exchanges on connect, so a blank broker
  rebuilds the topology automatically.
- All seven scheduled tasks in `CELERY_BEAT_SCHEDULE` are periodic (every 10
  minutes through daily). Nothing is a one-shot whose loss is permanent.

## What you actually lose

Tasks queued or in flight at the moment of the switch — in practice a plugin
security scan or Qt6 check triggered in the seconds around the restart, plus any
queued outbound email. All re-triggerable.

Do it at a quiet time. Nothing here touches user data.

## Procedure

All commands use `-p qgis-plugins`, matching `PROJECT_ID` in
`dockerize/Makefile`. That prefix decides the volume name, and getting it wrong
is easy: a bare `docker compose` run from `dockerize/` uses the directory name
instead and creates a *second*, unrelated `dockerize_rabbitmq` volume. Confirm
with `docker volume ls | grep rabbit` before removing anything.

```bash
cd dockerize

# 1. Stop the producers and let workers drain what they already have.
docker compose -p qgis-plugins stop uwsgi beat
docker compose -p qgis-plugins exec rabbitmq rabbitmqctl list_queues name messages
#    Wait until the durable queues (celery, qt6) read 0.

# 2. Stop the consumers.
docker compose -p qgis-plugins stop worker qgis-qt6

# 3. Replace the broker and its data directory.
docker compose -p qgis-plugins rm -sf rabbitmq
docker volume rm qgis-plugins_rabbitmq

# 4. Bring it back on 3.13 and wait for the healthcheck.
docker compose -p qgis-plugins up -d rabbitmq
docker compose -p qgis-plugins ps rabbitmq        # wait for "healthy"

# 5. Restart the application.
docker compose -p qgis-plugins up -d uwsgi worker beat qgis-qt6
```

## What it looks like if you skip step 3

The new node exits immediately and the container reports unhealthy, so anything
with `depends_on: service_healthy` (beat, qgis-qt6) refuses to start.
`make devweb` surfaces it as:

```
dependency failed to start: container qgis-plugins-rabbitmq-1 is unhealthy
```

That is this upgrade asking for step 3, not a broken image.

## Verifying

Check the pipeline, not just the container:

```bash
docker compose -p qgis-plugins exec rabbitmq rabbitmqctl version   # expect 3.13.x
docker compose -p qgis-plugins exec worker celery -A plugins inspect ping
docker compose -p qgis-plugins exec worker python -c "
import django; django.setup()
from plugins.tasks.update_qgis_versions import update_qgis_versions
r = update_qgis_versions.delay(); r.get(timeout=90); print(r.state)"
```

`inspect ping` should list the worker nodes and the task should reach `SUCCESS`.
Those two exercise the control and result paths — the ones 4.x breaks.

## Rollback

Set `RABBITMQ_IMAGE='rabbitmq:3.7-alpine'` in `dockerize/.env`, remove the
volume again (a 3.7 node will not read a 3.13 directory either), and
`docker compose -p qgis-plugins up -d rabbitmq`. Same drain-and-recreate shape.

## Verification done

On `rabbitmq:3.13.7-alpine`, after recreating the volume:

- container reaches `healthy` with the existing `rabbitmqctl status` healthcheck
- `celery -A plugins inspect ping` → `celery@uwsgi: OK / pong`, 2 nodes online
- a real task (`update_qgis_versions`) executed and returned `SUCCESS` through
  the `rpc://` result backend
- durable (`celery`, `qt6`) and transient (pidbox, `celeryev.*`) queues were all
  recreated automatically
- `make devweb` completes with every container healthy
