# Course-discovery Python 3.13 local runtime image.
#
# Mirrors the platform's `devstack/docker/py313/Dockerfile` shape: a digest-pinned
# python:3.13-slim-bookworm base, Debian/PyPI mirror ARGs, declared build deps,
# and a Node 16.20.2 stage (npm 8.19.4 is bundled with that Node, same pin as the
# platform py3.13 devstack and staging). Simplified to discovery's smaller surface:
# discovery is a single Django service, so there is no infra `/opt/venv`, no wheels
# multi-stage, and no RabbitMQ/Mongo/Elasticsearch client libraries to pre-build.
#
# The application itself is NOT baked in. `ops_discovery.py install` creates an
# isolated `/runtime/venv` (a durable named volume) and installs
# requirements/py313/local.txt into it at runtime. This image only declares the
# OS prerequisites for compiling that set (mysqlclient, lxml, cryptography) plus
# the Node toolchain that builds the Webpack frontend assets.
ARG PYTHON_IMAGE=python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72
ARG NODE_VERSION=16.20.2
ARG NODE_DIST_URL=https://nodejs.org/dist
ARG BUILD_DEPS="build-essential pkg-config default-libmysqlclient-dev libssl-dev libxml2-dev libxslt1-dev"

FROM ${PYTHON_IMAGE} AS base

# CN/offline builds can point the Debian mirrors at a local/tuna source.
ARG DEBIAN_MIRROR=http://deb.debian.org/debian
ARG DEBIAN_SECURITY_MIRROR=http://deb.debian.org/debian-security
RUN sed -i \
        -e "s|http://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|http://deb.debian.org/debian\$|${DEBIAN_MIRROR}|g" \
        -e "s|http://deb.debian.org/debian |${DEBIAN_MIRROR} |g" \
        /etc/apt/sources.list.d/debian.sources

# Node 16.20.2 (bundles npm 8.19.4) — same pin as the platform py3.13 devstack/staging.
FROM base AS node
ARG NODE_VERSION
ARG NODE_DIST_URL
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates xz-utils \
    && rm -rf /var/lib/apt/lists/* \
    && case "$(dpkg --print-architecture)" in \
        arm64) NODE_ARCH=arm64 ;; \
        amd64) NODE_ARCH=x64 ;; \
        *) echo "unsupported arch: $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac \
    && curl -fsSL --retry 3 --retry-delay 2 -o /tmp/node.tar.xz \
        "${NODE_DIST_URL}/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
    && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
    && rm -f /tmp/node.tar.xz

# Runtime: build deps for the app venv, plus Node/npm copied from the node stage,
# plus uv (which `ops_discovery.py install` uses to create /runtime/venv and
# install requirements/py313/local.txt into it). The platform's internal-delivery
# target pins uv==0.11.23; discovery's lock has no --require-hashes so any modern
# uv works, and 0.13.8 is the version the already-verified local environment uses.
FROM base
ARG BUILD_DEPS
ARG UV_VERSION=0.13.8
RUN apt-get update && apt-get install -y --no-install-recommends \
        ${BUILD_DEPS} curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "uv==${UV_VERSION}"
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm

# The app is run via `manage.py runserver`, dispatched by ops_discovery.py; the
# container just stays alive between commands.
CMD ["sleep", "infinity"]
