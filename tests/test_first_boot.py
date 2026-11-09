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


if __name__ == '__main__':
    unittest.main()
