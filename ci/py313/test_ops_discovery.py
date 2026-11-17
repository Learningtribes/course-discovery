"""Host-side (stdlib only) contract of the platform-runtime mapping in ops_discovery.py.

Run: uv run --no-project --python 3.13 python -B -m unittest ci/py313/test_ops_discovery.py
"""
import contextlib
import importlib.util
import io
import subprocess
import unittest
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location('ops_discovery', Path(__file__).with_name('ops_discovery.py'))


def load(platform_runtime):
    module = importlib.util.module_from_spec(SPEC)
    with mock.patch.dict('os.environ', {'DISCOVERY_PLATFORM_RUNTIME': platform_runtime}):
        SPEC.loader.exec_module(module)
    return module


def completed(stdout='', returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr='')


class PlatformRuntimeMapping(unittest.TestCase):
    shard = 1

    def setUp(self):
        super().setUp()
        stdout = contextlib.redirect_stdout(io.StringIO())
        stdout.__enter__()
        self.addCleanup(stdout.__exit__, None, None, None)

    def test_without_a_platform_runtime_nothing_is_mapped(self):
        ops = load('')
        with mock.patch.object(ops, 'docker') as docker:
            ops.map_platform_hosts()
        docker.assert_not_called()

    def test_hosts_line_points_lms_and_cms_at_the_platform_runtime(self):
        ops = load('platform-runtime')
        calls = []

        def docker(*args, check=True):
            calls.append(args)
            return completed('172.30.3.8\n' if args[0] == 'inspect' else '')

        with mock.patch.object(ops, 'docker', docker):
            ops.map_platform_hosts()
        self.assertEqual(calls[0][1], 'platform-runtime')
        self.assertIn("echo '172.30.3.8 lms cms'", calls[1][-1])
        self.assertEqual(calls[1][:3], ('exec', ops.RUNTIME, 'sh'))

    def test_missing_address_warns_and_does_not_write(self):
        ops = load('platform-runtime')
        calls = []

        def docker(*args, check=True):
            calls.append(args)
            return completed('')

        with mock.patch.object(ops, 'docker', docker):
            ops.map_platform_hosts()
        self.assertEqual([call[0] for call in calls], ['inspect'])

    def test_discovery_takes_only_its_own_alias_when_the_platform_runtime_is_set(self):
        ops = load('platform-runtime')
        calls = []

        def docker(*args, check=True):
            calls.append(args)
            if args[:2] == ('network', 'inspect'):
                return completed()
            if args[0] == 'inspect' and '-f' in args and 'Networks' in args[-1]:
                return completed('')
            return completed('172.30.3.8\n')

        with mock.patch.object(ops, 'docker', docker):
            ops.connect()
        connect = next(call for call in calls if call[:2] == ('network', 'connect'))
        self.assertEqual([connect[i + 1] for i, part in enumerate(connect) if part == '--alias'], ['discovery'])


if __name__ == '__main__':
    unittest.main()
