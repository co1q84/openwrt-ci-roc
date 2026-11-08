from pathlib import Path
import os
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
UPDATER = REPO / 'files/x86/usr/sbin/firmware-update'
CHECK = REPO / 'files/x86/usr/libexec/config-check'

# A fake uci: "get pkg.key" (any -c/-P/-q flags) answers from $UCI_STORE lines "pkg.key=value";
# the private copies' "fwmigNNN_" prefix maps back to the real package name.
FAKE_UCI = r'''#!/bin/sh
for a in "$@"; do last=$a; done
key=$(printf '%s' "$last" | sed 's/^fwmig[0-9]*_//')
line=$(grep -F -- "$key=" "$UCI_STORE" | head -n 1)
[ -n "$line" ] || exit 1
printf '%s\n' "${line#*=}"
'''

VALUES = '''network.lan.ipaddr=192.168.100.1/24
network.wan.proto=pppoe
network.wan.password=secret-dial-password
dropbear.@dropbear[0].Port=50222
openclash.config.enable=1
'''


class ConfigCheckTests(unittest.TestCase):
    def setup(self, directory):
        root = Path(directory)
        fake = root / 'bin'
        fake.mkdir()
        (fake / 'uci').write_text(FAKE_UCI)
        (fake / 'uci').chmod(0o755)
        store = root / 'store'
        store.write_text(VALUES)
        migration = root / 'migration'
        for name in ('network', 'dropbear', 'openclash'):
            (migration / 'etc/config').mkdir(parents=True, exist_ok=True)
            (migration / 'etc/config' / name).write_text('x\n')
        (migration / 'etc/tailscale').mkdir(parents=True)
        (migration / 'etc/tailscale/tailscaled.state').write_text('identity')
        live = root / 'live'
        (live / 'etc/tailscale').mkdir(parents=True)
        (live / 'etc/tailscale/tailscaled.state').write_text('identity')
        (live / 'etc/firmware-build.json').write_text('{"schema":1,"tag":"x86-64-9-1"}')
        env = dict(os.environ, PATH=f'{fake}:{os.environ["PATH"]}', UCI_STORE=str(store))
        return root, migration, live, store, env

    def write_expectations(self, root, migration, env, tag='x86-64-9-1'):
        script = f'. "{UPDATER}"; WORK="{root}/work"; mkdir -p "$WORK"; write_expectations "{migration}" {tag}'
        return subprocess.run(['sh', '-c', script], env=env, capture_output=True, text=True)

    def check(self, root, migration, live, env, *args):
        env = dict(env, ROOT=str(live), EXPECTED=str(migration / 'etc/firmware-update/expected'),
                   STATE_DIR=str(root / 'state'))
        return subprocess.run(['sh', str(CHECK), *args], env=env, capture_output=True, text=True)

    def test_restored_settings_pass_and_are_checked_once_per_firmware(self):
        with tempfile.TemporaryDirectory() as directory:
            root, migration, live, store, env = self.setup(directory)
            result = self.write_expectations(root, migration, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = (migration / 'etc/firmware-update/expected').read_text()
            self.assertNotIn('secret-dial-password', expected)
            self.assertIn('/etc/tailscale/tailscaled.state', expected)
            first = self.check(root, migration, live, env)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertTrue((root / 'state/last-check').read_text().startswith('OK'))
            store.write_text('')  # a second boot of the same firmware is not rechecked
            self.assertEqual(self.check(root, migration, live, env).returncode, 0)

    def test_lost_value_or_identity_is_reported_without_revealing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root, migration, live, store, env = self.setup(directory)
            self.write_expectations(root, migration, env)
            store.write_text(VALUES.replace('pppoe', 'dhcp').replace('secret-dial-password', 'other'))
            (live / 'etc/tailscale/tailscaled.state').unlink()
            result = self.check(root, migration, live, env)
            self.assertNotEqual(result.returncode, 0)
            report = (root / 'state/last-check').read_text()
            self.assertTrue(report.startswith('FAIL'))
            for item in ('network.wan.proto', 'network.wan.password', '/etc/tailscale/tailscaled.state'):
                self.assertIn(item, report)
            self.assertNotIn('dropbear', report)
            for secret in ('secret-dial-password', 'other', 'dhcp'):
                self.assertNotIn(secret, report + result.stdout + result.stderr)

    def test_expectations_for_another_firmware_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root, migration, live, store, env = self.setup(directory)
            self.write_expectations(root, migration, env, tag='x86-64-8-1')
            store.write_text('')
            result = self.check(root, migration, live, env)
            self.assertEqual(result.returncode, 0)
            self.assertFalse((root / 'state/last-check').exists())

    def test_service_runs_at_boot(self):
        link = REPO / 'files/x86/etc/rc.d/S99config-check'
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), '../init.d/config-check')


if __name__ == '__main__':
    unittest.main()
