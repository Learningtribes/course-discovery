# course-discovery py3.13 runtime image

Discovery's Python 3.13 development runtime is **not** built by Devstack. Devstack mounts
this checkout read-write into a container and drives it; the image only supplies the OS and
toolchain. Two consequences follow, and this directory owns both.

## 1. What the image contains

`Dockerfile` is the same shape as the platform's `devstack/docker/py313/Dockerfile`:

| Layer | Contents |
| --- | --- |
| base | digest-pinned `python:3.13-slim-bookworm`, Debian mirror build args |
| node | Node 16.20.2 (npm 8.19.4), the same pin as the platform devstack and staging |
| final | compile deps (`mysqlclient`, `lxml`, `cryptography`), `uv`, Node copied from `node` |

The application is deliberately **absent**. `requirements/py313/local.txt` is installed at
run time into an isolated venv inside the container, so changing application code or a lock
entry never requires rebuilding this image.

Build it locally with the Devstack entry point, which is the supported path:

```sh
cd <devstack> && make py313-build-discovery DISCOVERY_REPO=<this checkout>
```

`DISCOVERY_IMAGE` overrides the tag (`ltdps/discovery:py313-local` by default), and
`DEBIAN_MIRROR` / `DEBIAN_SECURITY_MIRROR` / `NODE_DIST_URL` override the Dockerfile defaults.

## 2. Publishing a released image

Devstack can consume a *release* of this image by digest, the same way it consumes
`ltdps/edxapp@sha256:...`. A digest reference is reproducible and reviewable; a mutable tag or
a machine-local image ID is neither. From a clean tree:

```sh
uv run --no-project --python 3.13 python -B ci/py313/build-runtime-image.py \
  --tag ltdps/discovery:py313-devstack-YYYYMMDD --context /new/dir
```

The script refuses `latest`/implicit tags, an existing remote tag and a dirty tree, builds
from `git archive HEAD` (committed content only), pushes a multi-platform OCI index
(`linux/amd64` + `linux/arm64`) with `docker buildx build --push`, reads the index back from
the registry and writes `runtime-image.lock.json`. Commit the lock in a follow-up commit.

Then a Devstack run can set:

```
discovery_image = ltdps/discovery@sha256:<index digest from the lock>
```

`docker run` pulls a digest reference on first use, so no extra Devstack step is needed.

## 3. Why the application is seeded separately

Two rows decide whether discovery can actually read courses from the run's LMS:

| Row | Written by | Why |
| --- | --- | --- |
| `oauth2_provider.Application` (LMS database) | platform `ci/py313/bringup/seed_discovery_oauth_app.py` | discovery authenticates with the client-credentials grant |
| `django_site` + `core_partner` (discovery database) | `ci/py313/seed_sites_and_partners.py` (this repo) | `refresh_course_metadata` raises `CommandError` on an empty `django_site`, and `core_partner` is the org-ownership backbone |

`seed_sites_and_partners.py` is invoked by the Devstack replay's `discovery.py seed()` step,
which is part of the normal `schema` stage. It is idempotent `update_or_create`, so
`make py313-update-db-discovery` re-runs it safely.

The site domain must be the **in-network** LMS address (`<run>-runtime:18000`), not the host
loopback mapping, because discovery runs in its own container.

## 4. Token type

The platform LMS resolves a `Bearer` token by `sha256(token)` against
`oauth2_provider.AccessToken.token_checksum`, so the opaque token returned for
`token_type=Bearer` authenticates while the JWT returned for `token_type=JWT` is rejected
with `token_nonexistent`. `course_discovery/settings/py313.py` therefore sets
`COURSES_API['TOKEN_TYPE'] = 'Bearer'`; the command default stays `JWT` so no other
deployment changes behaviour.

`course_metadata/views.py` still requests a JWT because it decodes the token to read
`preferred_username`, so that single-course refresh path is not aligned yet.

## 5. Production settings (`course_discovery.settings.production`)

`settings.py313` (section above) is the Devstack path and reads **only** environment
variables (`DB_*`, `CACHE_LOCATION`, `DISCOVERY_*`). A server deployed with the legacy
ansible layout instead runs `settings.production`, which reads two files and no `DB_*`
variables:

| Input | Read by | Notes |
| --- | --- | --- |
| `$DISCOVERY_CFG` or `$COURSE_DISCOVERY_CFG` | `production.py:28-35` | One of the two must be set, else `KeyError`. Every YAML key becomes a Django setting. |
| `<repo root>/discovery.auth.json` | `production.py:59` | Path is hard-coded off `PROJECT_ROOT`, not configurable. Must carry `ENGINE`, `NAME`, `USER`, `PASSWORD`, `HOST`, `PORT` — `DB_OVERRIDES` indexes all six, so a missing key raises `KeyError`. |

`/edx/app/discovery/discovery_env` (written by ansible) normally supplies both:

```sh
export DJANGO_SETTINGS_MODULE="course_discovery.settings.production"
export DISCOVERY_CFG="/edx/etc/discovery.yml"
```

### Precedence, and why editing both files misleads

`discovery.auth.json` **replaces** `DATABASES` wholesale after the YAML is applied, so a
`DATABASES` block in `discovery.yml` is dead weight — edit `discovery.auth.json`. Only
`DB_MIGRATION_{PASS,ENGINE,USER,NAME,HOST,PORT}` override it afterwards, per field.

`CACHES`, `SECRET_KEY`, `JWT_AUTH` and the rest come from the YAML. Neither `base.py` nor
`production.py` defines a `CACHES` default, so a YAML without one leaves Django with no
cache backend at all.

### Cache backend must change for Django 5.2

`django.core.cache.backends.memcached.MemcachedCache` was removed in Django 4.1; only
`PyMemcacheCache` (pymemcache) and `PyLibMCCache` (pylibmc) remain. A `discovery.yml`
carried over from the Django 1.11 deployment therefore fails at `django.setup()`, before any
database connection, because `django-parler` touches the cache at import time:

```
InvalidCacheBackendError: Could not find backend
'django.core.cache.backends.memcached.MemcachedCache':
Module "django.core.cache.backends.memcached" does not define a "MemcachedCache" attribute/class
```

Change the backend in `discovery.yml`. Do **not** hand-edit the Ansible output: use
`ci/py313/generate_discovery_config.py`, which writes a corrected copy into a
service-owned directory and refuses to emit a file that cannot start:

```sh
# run with the service venv so the backend class can be imported and proved to exist
/edx/app/discovery/venvs/discovery/bin/python ci/py313/generate_discovery_config.py \
    --source /edx/etc/discovery.yml \
    --out /edx/app/discovery/py313-config/discovery.yml \
    --print-env
# -> export DISCOVERY_CFG="/edx/app/discovery/py313-config/discovery.yml"
```

It rewrites **every** cache alias (a named alias left on `MemcachedCache` fails only when
something first reads it), sets `KEY_PREFIX: discovery-py313`, derives
`CELERY_RESULT_BACKEND: cache+memcached://<host>:11211/`, and preserves every other value in
the source file — this repository does not own the deployment's Elasticsearch URL, e-mail
host or partner id, so it must not rewrite them.

**Why a generated copy instead of an Ansible change.** The Platform hit the same wall and
solved it the same way: `platform/ci/py313/bringup/generate_aws_config.py` writes
`lms.env.json` / `cms.env.json` into a Platform-owned directory and the service is pointed at
it with `CONFIG_ROOT`; the Ansible output is not reused. Discovery follows that precedent
because it needs no change to the `configuration` repository, keeps this repository's `py3-master`
branch self-sufficient, and leaves a clean rollback: point `DISCOVERY_CFG` back at
`/edx/etc/discovery.yml`.

The `KEY_PREFIX` change is not cosmetic. `drf-extensions` pickles whole API responses into
the cache, so a key written by the python-memcached era cannot be unpickled by the new code —
that is a deserialisation error, not a cache miss (§2.4 of the upgrade plan).

`DISCOVERY_CFG` is an Ansible **role default** (`playbooks/roles/discovery/defaults/main.yml`),
so a py3.13 tenant can point it at the generated file from inventory alone
(`group_vars/<tenant>/vars.yml`), leaving the `configuration` repository untouched and the
Django 1.11 tenants on the old file.

The same backend migration applies to the platform's `lms.env.json` / `cms.env.json`
`CACHES`; for Platform this is already covered by `generate_aws_config.py`, so nothing in the
`configuration` repository changes there either.

### Verify before migrating

```sh
cd /edx/app/discovery/discovery
source /edx/app/discovery/discovery_env        # required; without it manage.py falls back to settings.local (SQLite)

python -c "
import django; django.setup()
from django.conf import settings
d = settings.DATABASES['default']
print(d['ENGINE'], d['HOST'], d['PORT'], d['NAME'], d['USER'], bool(d['PASSWORD']))
print(settings.CACHES['default']['BACKEND'])
print(settings.CACHES['default']['KEY_PREFIX'])
"
python manage.py showmigrations --plan | head   # reads the real database; pending list only, writes nothing
python manage.py migrate --noinput
```

`manage.py` defaults to `course_discovery.settings.local` (SQLite at
`course_discovery/default.db`). Running `manage.py migrate` without sourcing the env file
creates tables in a file, reports no error, and leaves MySQL empty.

The generator itself is covered by `ci/py313/test_generate_discovery_config.py` (14 tests):
every alias is rewritten, the source's unrelated values survive, a `MemcachedCache` or a
missing `CACHES` block is rejected, the file lands at mode 0640, and the source path can never
be overwritten in place.
