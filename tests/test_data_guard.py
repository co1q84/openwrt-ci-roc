import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / 'files/x86/usr/libexec/data-guard'
VNSTAT = REPO / 'files/x86/usr/libexec/vnstat-storage'
ERROR_LOG = REPO / 'files/x86/usr/libexec/error-log'
UPDATER = REPO / 'files/x86/usr/sbin/firmware-update'
PLACEHOLDER = 'data-missing /mnt/data tmpfs ro,relatime,size=4k,mode=555 0 0\n'


class DataGuardTests(unittest.TestCase):
    def guard(self, directory, ssd_enabled, mounts_text):
        root = Path(directory)
        bin_dir = root / 'bin'
        bin_dir.mkdir()
        calls = root / 'calls'
        stubs = {
            'uci': f'[ "$*" = "-q get fstab.ssd_data.enabled" ] && {{ echo {ssd_enabled}; exit 0; }}; exit 1',
            'mount': 'echo "mount $*" >> "$CALLS"',
            'logger': 'echo "logger $*" >> "$CALLS"',
        }
        for name, body in stubs.items():
            (bin_dir / name).write_text('#!/bin/sh\n' + body + '\n')
            (bin_dir / name).chmod(0o755)
        mounts = root / 'mounts'
        mounts.write_text(mounts_text)
        env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}', CALLS=str(calls),
                   PROC_MOUNTS=str(mounts), MOUNT=str(root / 'data'))
        result = subprocess.run(['sh', str(GUARD)], env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return calls.read_text() if calls.exists() else ''

    def test_missing_ssd_data_partition_is_covered_read_only(self):
        # Real failure: with the data partition absent, Docker created
        # /mnt/data/docker on the system overlay and could fill it.
        with tempfile.TemporaryDirectory() as directory:
            calls = self.guard(directory, 1, '/dev/loop0 /overlay f2fs rw 0 0\n')
            self.assertIn('mount -t tmpfs -o ro,size=4k,mode=0555 data-missing', calls)
            self.assertIn('daemon.err', calls)

    def test_mounted_data_partition_and_usb_only_systems_are_left_alone(self):
        for enabled, mounts in [(1, '/dev/sda4 {data} ext4 rw 0 0\n'), (0, '')]:
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as directory:
                calls = self.guard(directory, enabled, mounts.format(data=Path(directory) / 'data'))
                self.assertEqual(calls, '')

    def test_placeholder_is_not_mistaken_for_the_data_partition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mounts = root / 'mounts'
            mounts.write_text(PLACEHOLDER)
            conf = root / 'vnstat.conf'
            conf.write_text('')
            subprocess.run(['sh', str(VNSTAT)], check=True,
                           env=dict(os.environ, VNSTAT_CONF=str(conf), PROC_MOUNTS=str(mounts)))
            self.assertIn('DatabaseDir "/etc/vnstat"', conf.read_text())
            result = subprocess.run(['sh', str(ERROR_LOG)], text=True, capture_output=True,
                                    env=dict(os.environ, PROC_MOUNTS=str(mounts), LOG_DIR=str(root / 'log')))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / 'log').exists())
            result = subprocess.run(['sh', '-c', '. "$1"; data_mounted', 'test', str(UPDATER)],
                                    env=dict(os.environ, PROC_MOUNTS=str(mounts)))
            self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
