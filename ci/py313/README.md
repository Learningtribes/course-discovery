# course-discovery py3.13 runtime image

Discovery's Python 3.13 development runtime is **not** built by Devstack. Devstack mounts
this checkout read-write into a container and drives it; the image only supplies the OS and
toolchain. Two consequences follow, and this directory owns both.

## Production readiness of the dependency set

`requirements/py313/*.txt` are **hash-locked and reproducible, but installed only by the
devstack replay** today. Concretely:

- Every lock carries `--hash` entries (`uv pip compile --generate-hashes`), so an installer
  refuses any wheel or sdist whose digest differs from what was reviewed. The one non-PyPI
  input — the patched `edx-drf-extensions` sdist — is pinned by `--hash` from its archive bytes
  and by `companions/manifest.json` (upstream URL, patch name, and per-file digests).
- That archive is committed to git but is **not opaque**: `rebuild-companion.py` reconstructs
  it from the public upstream sdist plus the committed patch and verifies the bytes match, so a
  reviewer can reproduce the exact file.
- The `file://@COMPANIONS_DIR@/...` URL is not a devstack mount path; it is a placeholder that
  `materialize-lock.py` resolves for the environment at hand, verifying the archive before it
  writes a lock.
- There is **no production image and no production install path yet**: `ci/py313/Dockerfile`
  builds only the development base image, `requirements/py313/production.txt` is installed by
  nothing, and no staging/production deploy code exists. Until one does, treat these locks as
  devstack-replay-only despite being hash-locked.

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

That lock names its one non-PyPI input, the patched `edx-drf-extensions` sdist, with the
`@COMPANIONS_DIR@` placeholder instead of an absolute directory, so the same lock is valid
wherever the repository was checked out. `ci/py313/materialize-lock.py` resolves the
placeholder and writes the installable copy:

```sh
python ci/py313/materialize-lock.py requirements/py313/local.txt \
    --companions-dir "$PWD/ci/py313/companions/artifacts" \
    --output-dir /tmp/discovery-lock
uv pip install --python <venv>/bin/python -r /tmp/discovery-lock/local.txt
```

The script checks the archive against `ci/py313/companions/manifest.json` and refuses to
write a lock when the digest does not match, so an installer can never be pointed at bytes
nobody reviewed. The Devstack replay runs exactly this step
(`discovery.py install`, evidence label `install-discovery-lock`).

The replay uses `uv pip sync`, not `uv pip install`: the lock is the definition of that
environment, and `install` only adds, so a re-install after a lock change left behind the
packages the lock no longer listed.

### Regenerating a lock

`uv pip compile` cannot resolve `@COMPANIONS_DIR@` — it treats the value as a real directory.
`ci/py313/regenerate-lock.py` compiles against a temporary copy with the directory resolved,
then restores the placeholder and rewrites the header, so the committed file records a command
that works anywhere:

```sh
python ci/py313/regenerate-lock.py local                 # write requirements/py313/local.txt
python ci/py313/regenerate-lock.py base local production test
python ci/py313/regenerate-lock.py local --check          # exit 1 when the lock is stale
```

`--check` is the guard against the failure that motivated the script: `local.txt` had drifted
from `base.in` and still carried `django-rest-swagger` plus its five transitive dependencies
long after the input dropped them.

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

Both credentials authenticate; each has to be sent back under its own header prefix. The
platform LMS resolves a `Bearer` token by `sha256(token)` against
`oauth2_provider.AccessToken.token_checksum`, and a JWT by its signature, so a JWT sent as
`Bearer` answers `401 token_nonexistent` and a Bearer sent as `JWT` answers `401 Invalid token.`
Measured against the py3.13 LMS: the four token/prefix pairs separate cleanly into the two
matching ones (200) and the two crossed ones (401).

`course_discovery/settings/py313.py` sets `COURSES_API['TOKEN_TYPE'] = 'JWT'`, matching what
production resolves to: production reads `COURSES_API` from `discovery.auth.json`, which carries
no `TOKEN_TYPE` key, so `refresh_course_metadata` falls back to `JWT` — the same value
`lt-master` hardcodes. `DISCOVERY_COURSES_API_TOKEN_TYPE=Bearer` selects the opaque path for a
local experiment. The management command upper-cases the value before comparing it, so a
lower-case override cannot silently skip the `preferred_username` claim.

## 4a. Local-only guard

`settings.py313` enables `DEBUG`, sets `ALLOWED_HOSTS = ['*']` and can fall back to the JWT
secret `discovery-py313-jwt-secret-key`, which is published in this repository. Measured before
the guard: a token forged with that string was accepted with `administrator=True`. The module
therefore refuses to import unless `DISCOVERY_LOCAL_RUN=1`, and the Devstack replay writes that
into the container environment. Anything shared or deployed must use
`course_discovery.settings.production` instead.

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

**The `LOCATION` address is preserved, and checked.** It belongs to the deployment, so the
generator never invents one. It does resolve each host and prints a warning when one does not
answer, because the failure it leaves behind is not local to this file: a `LOCATION:
['memcache']` copied out of a devstack resolves nowhere else, `django.setup()` still
succeeds (pymemcache connects lazily), and the first request that touches the cache returns
500 with nothing pointing back here. The warning names `DISCOVERY_MEMCACHE` (already
supported by `cache_locations`) as the override. It is a warning and not a failure on
purpose: the generator may legitimately run on a host whose name resolution differs from the
service host, and blocking a deployment over that would be worse than saying it once.

**Why a generated copy instead of an Ansible change.** The Platform hit the same wall and
solved it the same way: `platform/ci/py313/bringup/generate_aws_config.py` writes
`lms.env.json` / `cms.env.json` into a Platform-owned directory and the service is pointed at
it with `CONFIG_ROOT`; the Ansible output is not reused. Discovery follows that precedent
because it needs no change to the `configuration` repository, keeps this repository's `py3-master`
branch self-sufficient, and leaves a clean rollback: point `DISCOVERY_CFG` back at
`/edx/etc/discovery.yml`.

### Browser login keys must change for the EdXOAuth2 backend

`AUTHENTICATION_BACKENDS` names `auth_backends.backends.EdXOAuth2`, and that backend declares
`name = 'edx-oauth2'`. social-auth derives its settings prefix from that name, so it reads
`SOCIAL_AUTH_EDX_OAUTH2_KEY` / `_SECRET` / `_URL_ROOT`, plus `_PUBLIC_URL_ROOT` (the
redirect base) and `_LOGOUT_REDIRECT_URL`. The `EdXOpenIdConnect` backend that read
`SOCIAL_AUTH_EDX_OIDC_*` is gone, and those keys are now ignored.

The Ansible role still writes the old names, so a `discovery.yml` carried over from the
Django 1.11 deployment configures nothing: browser login to `/admin` and the discovery UI fails
while JWT and Bearer API traffic keeps working, which makes the failure easy to miss.
`generate_discovery_config.py` renames the keys in the copy it writes, so the file the service
actually reads (`$DISCOVERY_CFG`) carries the names the backend looks for:

| Ansible writes | The backend reads |
| --- | --- |
| `SOCIAL_AUTH_EDX_OIDC_KEY` | `SOCIAL_AUTH_EDX_OAUTH2_KEY` |
| `SOCIAL_AUTH_EDX_OIDC_SECRET` | `SOCIAL_AUTH_EDX_OAUTH2_SECRET` |
| `SOCIAL_AUTH_EDX_OIDC_URL_ROOT` | `SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT` |
| `SOCIAL_AUTH_EDX_OIDC_LOGOUT_URL` | `SOCIAL_AUTH_EDX_OAUTH2_LOGOUT_REDIRECT_URL` |
| `SOCIAL_AUTH_EDX_OIDC_PUBLIC_URL_ROOT` | `SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT` |
| `SOCIAL_AUTH_EDX_OIDC_ID_TOKEN_DECRYPTION_KEY` | dropped — the OAuth2 backend has no equivalent |

The logout key is `_LOGOUT_REDIRECT_URL`, not `_LOGOUT_URL`: `EdXOAuth2` reads
`self.setting('LOGOUT_REDIRECT_URL')`, so the shorter name would be written and never read.

The two `*_URL_ROOT` values are **normalized**: a trailing `/oauth2` or `/oauth` mount is
stripped. `EdXOAuth2` builds its endpoints itself -- `f'{url_root}/oauth2/authorize'` and
`f"{self.setting('URL_ROOT')}/oauth2/access_token"` -- so an Ansible value that already ends in
`/oauth2` would produce `/oauth2/oauth2/authorize` and `/oauth2/oauth2/access_token`. Stripping
is safe in both directions: a root without the mount is unchanged.

The generator refuses to write a file whose `_OAUTH2_KEY` has no `_URL_ROOT` to redirect to.
A key already under the new name wins, so re-running over an already-corrected file is a no-op
rather than a way to restore a stale value.

A `SOCIAL_AUTH_EDX_OIDC_*` key the table above does not cover (an old-backend setting with no
OAuth2 equivalent) is **reported on stderr and dropped**, not treated as an error: an extra
harmless key in an Ansible file must not stop the generator, because the file it writes is what
lets the service start at all. A key that the rename table *does* cover can only survive there
through a bug in `apply_oauth2_backend`, and that is a hard failure.

`DISCOVERY_SOCIAL_AUTH_EDX_OAUTH2_*` are also present in
`hawthorn_inventory/group_vars/tenants/discovery-vars.yml`, next to the old names the role still
maps, so a role update has the data it needs without an inventory change at the same time.

A login smoke test against a py3.13 LMS is still required before cutover: the generator proves
the keys are spelled correctly, not that the OAuth2 application behind them is registered.


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

The generator itself is covered by `ci/py313/test_generate_discovery_config.py` (34 tests):
every alias is rewritten, both URL roots lose a trailing OAuth2 mount, the source's unrelated
values survive, a `MemcachedCache` or a missing `CACHES` block is rejected, the file lands at
mode 0640, and the source path can never be overwritten in place.
