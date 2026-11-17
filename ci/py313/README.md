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
