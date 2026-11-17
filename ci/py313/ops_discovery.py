#!/usr/bin/env python3
"""Manage and start the course-discovery Python 3.13 local environment.

Mirrors the platform's `ops/ops.py` pattern, adapted to discovery's three
containers (runtime + MySQL 8.4 + memcached). Runs on the host and drives the
containers via `docker`.

Commands:
  create   idempotently create the network, volumes and three containers
  install  create the isolated /runtime/venv and install requirements/py313/local.txt
  connect  attach the runtime to the platform network (discovery/lms/cms aliases)
  migrate  apply migrations with the py313 (MySQL) settings
  up       start containers and dispatch the runserver process
  start    start containers only (no runserver)
  down     stop the runtime process + containers (keeps data)
  status   show container state, running processes, and health
  health   HTTP-check the discovery service
  seed     idempotently seed django_site + core_partner (LMS data-fetch mapping)
  shell    interactive bash inside the runtime container (settings identity)

Containers (names are fixed by the local environment contract):
  discovery-py3-runtime    Python 3.13 + course-discovery repo (mounted at /workspace)
  discovery-py3-mysql      MySQL 8.4.13 (host 13306 -> 3306)
  discovery-py3-memcached  memcached 1.6.45 (host 11212 -> 11211)

Secrets are never embedded here:
  * the MySQL password is read from $DISCOVERY_PRIVATE_DIR/mysql-root-password
    (default: <repo>/../private/mysql-root-password), which the container also
    mounts at /private/mysql-root-password;
  * the platform LMS JWT secret for interop is passed via
    $DISCOVERY_LMS_JWT_SECRET (optional; omit for a standalone discovery).
"""
import os
import subprocess
import sys
import time
from pathlib import Path

# Container/network/volume names, overridable so a throwaway identity can be
# exercised without touching the live one (mirrors the platform's
# PY313_RUNTIME_CONTAINER override in probe/startup-*/runtime_process.py).
def _name(key, default):
    return os.environ.get(key, default)


RUNTIME = _name("DISCOVERY_RUNTIME_CONTAINER", "discovery-py3-runtime")
MYSQL = _name("DISCOVERY_MYSQL_CONTAINER", "discovery-py3-mysql")
MEMCACHED = _name("DISCOVERY_MEMCACHED_CONTAINER", "discovery-py3-memcached")
SERVICES = (MYSQL, MEMCACHED)
NETWORK = _name("DISCOVERY_NETWORK", "discovery-py3")

SETTINGS_MODULE = "course_discovery.settings.py313"
REPO_MOUNT = "/workspace"
PORT = "8000"
# Isolated application venv (mirrors the platform's /runtime/venv, created and
# populated by `install`). Never run the app from the image's global site-packages.
APP_PYTHON = "/runtime/venv/bin/python"
LOCAL_LOCK = "requirements/py313/local.txt"

# Image pins used by `create`. The runtime image is built locally from
# ci/py313/Dockerfile (`docker build -f ci/py313/Dockerfile -t <image> .`).
RUNTIME_IMAGE = _name("DISCOVERY_RUNTIME_IMAGE", "ltdps/discovery:py313-local")
MYSQL_IMAGE = "mysql:8.4.13"
MEMCACHED_IMAGE = "memcached:1.6.45"
MYSQL_VOLUME = _name("DISCOVERY_MYSQL_VOLUME", "discovery-py3-mysql-data")
# Durable /runtime volume: holds the venv so it survives `docker rm` of the
# runtime container (mirrors the platform's *_runtime-volume).
RUNTIME_VOLUME = _name("DISCOVERY_RUNTIME_VOLUME", "discovery-py3-runtime-volume")
MYSQL_HOST_PORT = os.environ.get("DISCOVERY_MYSQL_PORT", "13306")
MEMCACHED_HOST_PORT = os.environ.get("DISCOVERY_MEMCACHED_PORT", "11212")
RUNTIME_HOST_PORT = os.environ.get("DISCOVERY_RUNTIME_PORT", "18381")

# The platform py3.13 network + the aliases discovery needs there so LMS/CMS can
# reach it as `http://discovery:8000`. Attached by `connect`, not `create`.
PLATFORM_NETWORK = os.environ.get("DISCOVERY_PLATFORM_NETWORK", "py313-sync1029r1")
PLATFORM_ALIASES = ("discovery", "lms", "cms")
# When the platform runs LMS and CMS in ONE container (the replay layout), discovery must not take the
# `lms`/`cms` aliases itself (it would answer its own requests); it takes `discovery` only and resolves
# `lms`/`cms` to that container (names the platform ALLOWED_HOSTS accepts). Empty keeps the alias behaviour above.
PLATFORM_RUNTIME = os.environ.get("DISCOVERY_PLATFORM_RUNTIME", "")


# Where the container's /private dir lives on the host (holds mysql-root-password).
DEFAULT_PRIVATE_DIR = Path(__file__).resolve().parents[3] / "private"


def private_dir():
    return Path(os.environ.get("DISCOVERY_PRIVATE_DIR", DEFAULT_PRIVATE_DIR))


def mysql_password():
    pw = os.environ.get("DB_PASSWORD")
    if pw:
        return pw
    pw_file = private_dir() / "mysql-root-password"
    if pw_file.is_file():
        return pw_file.read_text().strip()
    # Fall back to reading it from inside the container (already mounted at /private).
    r = docker("exec", RUNTIME, "cat", "/private/mysql-root-password", check=False)
    return r.stdout.strip()


def docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def running(container):
    r = docker("inspect", "-f", "{{.State.Running}}", container, check=False)
    return r.returncode == 0 and r.stdout.strip() == "true"


def container_exists(container):
    return docker("inspect", container, check=False).returncode == 0


def _ensure(kind, name):
    """Create a network/volume only when absent; never re-create over live state."""
    if docker(kind, "inspect", name, check=False).returncode == 0:
        print("%s exists:  %s" % (kind, name))
        return
    docker(kind, "create", name)
    print("%s created: %s" % (kind, name))


def create():
    """Idempotently create the network, volumes and three containers.

    Safe to re-run: existing containers are left alone (so a live MySQL data
    volume is never re-initialised). To migrate an existing runtime container to
    the durable /runtime volume, run `docker rm -f <runtime>` first, then `create`
    again — the MySQL named volume keeps the schema intact.
    """
    _ensure("network", NETWORK)
    _ensure("volume", MYSQL_VOLUME)
    _ensure("volume", RUNTIME_VOLUME)

    pw = mysql_password()
    if not pw:
        raise SystemExit("MySQL password not found; create %s first." % (private_dir() / "mysql-root-password"))

    if container_exists(MYSQL):
        print("container exists:  %s" % MYSQL)
    else:
        docker("run", "-d", "--name", MYSQL, "--network", NETWORK,
               "-e", "MYSQL_ROOT_PASSWORD=%s" % pw,
               "-e", "MYSQL_PASSWORD=%s" % pw,
               "-e", "MYSQL_USER=discovery",
               "-e", "MYSQL_DATABASE=discovery",
               "-p", "%s:3306" % MYSQL_HOST_PORT,
               "-v", "%s:/var/lib/mysql" % MYSQL_VOLUME,
               MYSQL_IMAGE)
        print("container created: %s" % MYSQL)

    if container_exists(MEMCACHED):
        print("container exists:  %s" % MEMCACHED)
    else:
        docker("run", "-d", "--name", MEMCACHED, "--network", NETWORK,
               "-p", "%s:11211" % MEMCACHED_HOST_PORT, MEMCACHED_IMAGE)
        print("container created: %s" % MEMCACHED)

    if container_exists(RUNTIME):
        print("container exists:  %s" % RUNTIME)
    else:
        repo = Path(__file__).resolve().parents[2]
        docker("run", "-d", "--name", RUNTIME, "--network", NETWORK,
               "-p", "%s:%s" % (RUNTIME_HOST_PORT, PORT),
               "-v", "%s:%s" % (repo, REPO_MOUNT),
               "-v", "%s:/private" % private_dir(),
               "-v", "%s:/runtime" % RUNTIME_VOLUME,
               RUNTIME_IMAGE)
        print("container created: %s" % RUNTIME)


def connect():
    """Attach the runtime to the platform network with the discovery/lms/cms aliases.

    The platform py3.13 LMS/CMS reach discovery as `http://discovery:8000`, so the
    alias must exist on that network. Idempotent: re-attaching an existing
    endpoint is a no-op.
    """
    if docker("network", "inspect", PLATFORM_NETWORK, check=False).returncode != 0:
        raise SystemExit("platform network %r does not exist; is the py3.13 platform up?"
                         % PLATFORM_NETWORK)
    current = docker("inspect", RUNTIME, "-f",
                     "{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{println}}{{end}}",
                     check=False).stdout.split()
    if PLATFORM_NETWORK in current:
        print("already attached to %s (aliases %s)" % (PLATFORM_NETWORK, ", ".join(PLATFORM_ALIASES)))
        return
    aliases = ("discovery",) if PLATFORM_RUNTIME else PLATFORM_ALIASES
    args = ["network", "connect"]
    for alias in aliases:
        args += ["--alias", alias]
    args += [PLATFORM_NETWORK, RUNTIME]
    docker(*args)
    print("attached %s to %s as %s" % (RUNTIME, PLATFORM_NETWORK, ", ".join(aliases)))
    map_platform_hosts()


def map_platform_hosts():
    """Point `lms`/`cms` at the platform runtime container inside the discovery runtime.

    /etc/hosts of a container is rebuilt on every stop/start, so this runs after each start. No-op unless
    DISCOVERY_PLATFORM_RUNTIME names the platform container.
    """
    if not PLATFORM_RUNTIME:
        return
    ip = docker("inspect", PLATFORM_RUNTIME, "-f",
                '{{(index .NetworkSettings.Networks "%s").IPAddress}}' % PLATFORM_NETWORK, check=False).stdout.strip()
    if not ip:
        print("WARNING: %s has no address on network %s; lms/cms are not mapped" % (PLATFORM_RUNTIME, PLATFORM_NETWORK))
        return
    docker("exec", RUNTIME, "sh", "-c",
           "grep -v ' lms cms$' /etc/hosts > /tmp/hosts.new; echo '%s lms cms' >> /tmp/hosts.new; cat /tmp/hosts.new > /etc/hosts" % ip)
    print("%s resolves lms, cms -> %s (%s)" % (RUNTIME, ip, PLATFORM_RUNTIME))


def migrate():
    """Apply migrations with the py313 (MySQL) settings from the isolated venv.

    Starts the backing services first: migrations are the first command that
    actually needs MySQL, and a stopped `discovery-py3-mysql` would otherwise
    surface as a DNS error ('Unknown server host') rather than a clear one.
    """
    if not start_containers():
        raise SystemExit("MySQL not ready; see `docker logs %s`." % MYSQL)
    _run_in_runtime(APP_PYTHON, "manage.py", "migrate", "--noinput")


def _run_in_runtime(*argv):
    cmd = ["docker", "exec", "-w", REPO_MOUNT]
    for key, val in base_env().items():
        cmd += ["-e", "%s=%s" % (key, val)]
    cmd += [RUNTIME, *argv]
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        raise SystemExit("command failed (exit %d): %s" % (r.returncode, " ".join(argv)))


def runtime_processes():
    """Return the PIDs of the actual `manage.py runserver` process inside the runtime container."""
    code = (
        "import os\n"
        "out = []\n"
        "for p in os.listdir('/proc'):\n"
        "    if not p.isdigit():\n"
        "        continue\n"
        "    try:\n"
        "        with open('/proc/%s/cmdline' % p, 'rb') as f:\n"
        "            cmd = f.read().replace(b'\\x00', b' ').decode(errors='ignore')\n"
        "    except OSError:\n"
        "        continue\n"
        "    if 'manage.py runserver' in cmd and 'python -c' not in cmd:\n"
        "        out.append(p)\n"
        "print('\\n'.join(out))\n"
    )
    r = docker("exec", RUNTIME, "python3", "-c", code, check=False)
    return [l for l in r.stdout.splitlines() if l.strip()]


def base_env():
    env = {
        "DB_PASSWORD": mysql_password(),
        "DB_HOST": MYSQL,
        "DJANGO_SETTINGS_MODULE": SETTINGS_MODULE,
    }
    # DB identity overrides (py313.py reads all of these from the environment).
    for key in ("DB_NAME", "DB_USER", "DB_PORT", "CACHE_LOCATION"):
        if key in os.environ:
            env[key] = os.environ[key]
    # Optional platform-LMS interop (phase 6a). Only forwarded when set.
    for key in ("DISCOVERY_LMS_JWT_SECRET", "DISCOVERY_LMS_JWT_ISSUER", "DISCOVERY_LMS_JWT_AUDIENCE",
                "DISCOVERY_OIDC_KEY", "DISCOVERY_OIDC_SECRET"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def start_containers():
    """Start MySQL, memcached and the runtime; wait for MySQL to answer."""
    for c in (MYSQL, MEMCACHED, RUNTIME):
        if not running(c):
            docker("start", c)
    if PLATFORM_RUNTIME and docker("network", "inspect", PLATFORM_NETWORK, check=False).returncode == 0:
        map_platform_hosts()
    deadline = time.time() + 120
    while time.time() < deadline:
        r = docker("exec", MYSQL, "sh", "-c",
                   'mysqladmin ping -h localhost -uroot -p"$MYSQL_ROOT_PASSWORD" 2>&1', check=False)
        if "alive" in r.stdout:
            return True
        time.sleep(3)
    return False


def dispatch_runserver():
    cmd = ["docker", "exec", "-d", "-w", REPO_MOUNT]
    for key, val in base_env().items():
        cmd += ["-e", "%s=%s" % (key, val)]
    cmd += [RUNTIME, "sh", "-c",
            "%s manage.py runserver 0.0.0.0:%s --noreload >> /tmp/discovery-runserver.log 2>&1" % (APP_PYTHON, PORT)]
    subprocess.run(cmd, check=True)


def install():
    """Create the isolated /runtime/venv and install the local lock into it.

    Mirrors the platform install.sh entry point (`uv venv --python ... /runtime/venv`
    then `uv pip install --python /runtime/venv/bin/python ...` then `uv pip check`),
    simplified because discovery has no editable platform packages and no hash-pinned
    runtime bootstrap: the whole dependency set (app + test tools) resolves from
    requirements/py313/local.txt, whose one non-PyPI entry (edx-drf-extensions) is a
    file:// URL pointing at the companion artifact under /workspace.
    """
    if not running(RUNTIME):
        docker("start", RUNTIME)
    docker("exec", RUNTIME, "sh", "-c",
           "test -x %s || uv venv --python /usr/local/bin/python3.13 /runtime/venv" % APP_PYTHON)
    print("Installing %s into /runtime/venv (this can take several minutes) ..." % LOCAL_LOCK)
    r = subprocess.run(["docker", "exec", "-w", REPO_MOUNT, RUNTIME, "sh", "-c",
                        "uv pip install --python %s -r %s" % (APP_PYTHON, LOCAL_LOCK)], check=False)
    if r.returncode != 0:
        raise SystemExit("uv pip install failed (exit %d); see output above." % r.returncode)
    docker("exec", RUNTIME, "sh", "-c",
           "uv pip check --python %s && echo 'pip check: OK'" % APP_PYTHON)


def up():
    ready = start_containers()
    if runtime_processes():
        print("runserver already running; use 'status' or 'down' first.")
        return
    dispatch_runserver()
    print("discovery HTTP dispatched (port %s); health check required." % PORT)
    print("MySQL ready" if ready else "MySQL not ready within 120s (see docker logs).")


def start():
    ready = start_containers()
    print("Containers started." + (" MySQL ready." if ready else " MySQL not ready within 120s."))


def down():
    for pid in runtime_processes():
        docker("exec", RUNTIME, "kill", pid, check=False)
    for c in (RUNTIME, MYSQL, MEMCACHED):
        docker("stop", c, check=False)
    print("Stopped runtime and services; containers, volumes and data kept.")


def status():
    for c in (SERVICES + (RUNTIME,)):
        state = "Up" if running(c) else "Exited/stopped"
        print("%-28s %s" % (c, state))
    procs = runtime_processes()
    if not running(RUNTIME):
        print("runtime is not running")
        return
    print("runserver processes:", procs or "none")
    health()


def health():
    r = docker("exec", RUNTIME, "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
               "http://127.0.0.1:%s/health/" % PORT, check=False)
    print("/health/ ->", r.stdout.strip())


def seed():
    """Idempotently seed django_site + core_partner (see ci/py313/seed_sites_and_partners.py)."""
    cmd = ["docker", "exec", "-w", REPO_MOUNT]
    for key, val in base_env().items():
        cmd += ["-e", "%s=%s" % (key, val)]
    cmd += [RUNTIME, APP_PYTHON, "ci/py313/seed_sites_and_partners.py"]
    # Use check=False and inspect stderr ourselves: with check=True the
    # CalledProcessError would echo the full argv (including the DB password).
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        raise SystemExit("seed failed (exit %d); see stderr above." % r.returncode)


def shell():
    env = base_env()
    export = " ".join("export %s='%s'" % (k, v) for k, v in env.items())
    cmd = (
        "export PATH=/runtime/venv/bin:$PATH; %s; cd %s; "
        "echo '=== discovery py313 shell: %s (settings=%s) ==='; "
        "echo 'python     : /runtime/venv/bin/python'; "
        "echo 'manage.py  : python manage.py <cmd>'; "
        "echo 'shell      : python manage.py shell'; "
        "echo 'tests      : python manage.py test <app> (see ci/py313/run_tests_mysql.sh)'; "
        "exec bash"
    ) % (export, REPO_MOUNT, REPO_MOUNT, SETTINGS_MODULE)
    argv = ["docker", "exec", "-it", "-w", REPO_MOUNT, RUNTIME, "sh", "-c", cmd]
    os.execvp("docker", argv)


def usage():
    print(__doc__)


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "create":
        create()
    elif action == "install":
        install()
    elif action == "connect":
        connect()
    elif action == "migrate":
        migrate()
    elif action == "up":
        up()
    elif action == "start":
        start()
    elif action == "down":
        down()
    elif action == "status":
        status()
    elif action == "health":
        health()
    elif action == "seed":
        seed()
    elif action == "shell":
        shell()
    else:
        usage()
        raise SystemExit(
            "usage: ops_discovery.py create|install|connect|migrate|up|start|down|status|health|seed|shell")
