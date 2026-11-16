#!/bin/bash
# MySQL 8.4 test job (phase 5 S5.2).
#
# Runs the Django test suite against a real MySQL 8.4 server instead of the
# SQLite in-memory default from `course_discovery/settings/test.py`. SQLite
# cannot catch MySQL-specific schema/index problems (e.g. utf8mb4 index length
# 1071), so this job is required before phase 6a.
#
# Connection settings come from the environment (all optional):
#   DB_HOST      default discovery-py3-mysql
#   DB_PORT      default 3306
#   DB_USER      default root
#   DB_PASSWORD  default: read from /private/mysql-root-password when present
#   DB_NAME      default discovery (Django runs migrations against test_<NAME>)
#
# Reuses the test database across runs (--reuse-db) for speed; drop the
# test_discovery database to force a fresh schema rebuild.

set -euo pipefail

DB_HOST="${DB_HOST:-discovery-py3-mysql}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-root}"
DB_NAME="${DB_NAME:-discovery}"

if [ -z "${DB_PASSWORD:-}" ] && [ -f /private/mysql-root-password ]; then
    DB_PASSWORD="$(cat /private/mysql-root-password)"
fi

export DB_ENGINE=django.db.backends.mysql
export DB_NAME DB_USER DB_PASSWORD DB_HOST DB_PORT

exec python3 -m pytest -p no:cacheprovider --reuse-db \
    --ds=course_discovery.settings.test \
    "${@}"
