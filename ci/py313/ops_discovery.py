#!/usr/bin/env python3
"""Manage and start the course-discovery Python 3.13 local environment.

Mirrors the platform's `ops/ops.py` pattern, adapted to discovery's three
containers (runtime + MySQL 8.4 + memcached). Runs on the host and drives the
containers via `docker`.

Commands:
  up       start containers and dispatch the runserver process
  start    start containers only (no runserver)
  down     stop the runtime process + containers (keeps data)
  status   show container state, running processes, and health
  health   HTTP-check the discovery service
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

RUNTIME = "discovery-py3-runtime"
MYSQL = "discovery-py3-mysql"
MEMCACHED = "discovery-py3-memcached"
SERVICES = (MYSQL, MEMCACHED)

SETTINGS_MODULE = "course_discovery.settings.py313"
REPO_MOUNT = "/workspace"
PORT = "8000"

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
        "    if cmd.startswith('python3 manage.py runserver'):\n"
        "        out.append(p)\n"
        "print('\\n'.join(out))\n"
    )
    r = docker("exec", RUNTIME, "python3", "-c", code, check=False)
    return [l for l in r.stdout.splitlines() if l.strip()]


def base_env():
    env = {
        "DB_PASSWORD": mysql_password(),
        "DJANGO_SETTINGS_MODULE": SETTINGS_MODULE,
    }
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
            "python3 manage.py runserver 0.0.0.0:%s --noreload >> /tmp/discovery-runserver.log 2>&1" % PORT]
    subprocess.run(cmd, check=True)


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


def shell():
    env = base_env()
    export = " ".join("export %s='%s'" % (k, v) for k, v in env.items())
    cmd = (
        "%s; cd %s; "
        "echo '=== discovery py313 shell: %s (settings=%s) ==='; "
        "echo 'manage.py  : python3 manage.py <cmd>'; "
        "echo 'shell      : python3 manage.py shell'; "
        "echo 'tests      : python3 manage.py test <app> (see ci/py313/run_tests_mysql.sh)'; "
        "exec bash"
    ) % (export, REPO_MOUNT, REPO_MOUNT, SETTINGS_MODULE)
    argv = ["docker", "exec", "-it", "-w", REPO_MOUNT, RUNTIME, "sh", "-c", cmd]
    os.execvp("docker", argv)


def usage():
    print(__doc__)


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "up":
        up()
    elif action == "start":
        start()
    elif action == "down":
        down()
    elif action == "status":
        status()
    elif action == "health":
        health()
    elif action == "shell":
        shell()
    else:
        usage()
        raise SystemExit("usage: ops_discovery.py up|start|down|status|health|shell")
