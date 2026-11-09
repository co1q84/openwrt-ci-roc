from pathlib import Path
import os
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
VNSTAT = REPO / 'files/x86/etc/uci-defaults/80-vnstat-wan'


class VnstatDefaultsTests(unittest.TestCase):
    def run_defaults(self, directory, conf_text, interface=''):
        root = Path(directory)
        conf = root / 'vnstat.conf'
        conf.write_text(conf_text)
        fake = root / 'bin'
        fake.mkdir(exist_ok=True)
        calls = root / 'calls'
        (fake / 'uci').write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n'
                                  'case "$*" in *" get "*) printf "%s" "$IFACE"; [ -n "$IFACE" ];; esac\n')
        (fake / 'uci').chmod(0o755)
        env = dict(os.environ, PATH=f'{fake}:{os.environ["PATH"]}', VNSTAT_CONF=str(conf),
                   CALLS=str(calls), IFACE=interface)
        result = subprocess.run(['sh', str(VNSTAT)], env=env, capture_output=True, text=True)
        return result, conf.read_text(), calls.read_text() if calls.exists() else ''

    def test_wan_port_is_counted_and_storage_is_left_to_boot_time_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            stock = ';DatabaseDir "/var/lib/vnstat"\n'
            result, text, calls = self.run_defaults(directory, stock)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('add_list vnstat.@vnstat[0].interface=eth0', calls)
            self.assertEqual(text, stock)

    def test_user_interface_choice_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _, calls = self.run_defaults(directory, '', interface='br-lan')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('add_list', calls)


DOCKER = REPO / 'files/x86/etc/uci-defaults/82-x86-docker-off'


class DockerDefaultTests(unittest.TestCase):
    def run_default(self, directory, data_root, containers=False, marker=''):
        root = Path(directory)
        store = root / 'docker'
        if containers:
            (store / 'containers' / 'abc').mkdir(parents=True)
        calls = root / 'calls'
        init = root / 'dockerd'
        init.write_text('#!/bin/sh\necho "init $*" >> "$CALLS"\n')
        init.chmod(0o755)
        bin_dir = root / 'bin'
        bin_dir.mkdir()
        (bin_dir / 'uci').write_text(
            '#!/bin/sh\necho "uci $*" >> "$CALLS"\ncase "$*" in\n'
            '  "-q get system.x86_defaults.docker_off") [ -n "$MARKER" ] && echo "$MARKER";;\n'
            '  "-q get dockerd.globals.data_root") echo "$ROOT";;\n'
            '  "-q get system.x86_defaults") exit 1;;\nesac\nexit 0\n')
        (bin_dir / 'uci').chmod(0o755)
        env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}', CALLS=str(calls), DOCKERD_INIT=str(init),
                   MARKER=marker, ROOT=data_root.replace('STORE', str(store)))
        result = subprocess.run(['sh', str(DOCKER)], env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return calls.read_text() if calls.exists() else ''

    def test_unused_docker_is_disabled_once(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = self.run_default(directory, 'STORE/')
            self.assertIn('init disable', calls)
            self.assertIn('uci -q set system.x86_defaults.docker_off=1', calls)

    def test_docker_in_use_or_reenabled_or_on_ssd_is_left_alone(self):
        for kwargs in [dict(data_root='STORE/', containers=True), dict(data_root='STORE/', marker='1'),
                       dict(data_root='/mnt/data/docker/')]:
            with self.subTest(**kwargs), tempfile.TemporaryDirectory() as directory:
                self.assertNotIn('init disable', self.run_default(directory, **kwargs))


if __name__ == '__main__':
    unittest.main()
