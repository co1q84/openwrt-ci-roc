from pathlib import Path
import os
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'files/x86/usr/libexec/error-log'
INIT = REPO / 'files/x86/etc/init.d/error-log'

LINES = '''Sun Nov  8 16:17:49 2026 daemon.err tailscaled[4137]: magicsock: new contact
Sun Nov  8 16:18:01 2026 kern.warn kernel: [  3.1] ntfs3(sda2): volume is dirty
Sun Nov  8 16:18:02 2026 daemon.info dnsmasq[1]: cleared cache
Sun Nov  8 16:18:03 2026 daemon.notice watchcat[99]: Could not reach 223.5.5.5, rebooting
Sun Nov  8 16:18:04 2026 kern.err kernel: Out of memory: Killed process 42 (clash)
Sun Nov  8 16:18:05 2026 user.notice root: ordinary note
'''


class ErrorLogTests(unittest.TestCase):
    def run_log(self, directory, lines, max_bytes='1048576', mounted=True, follow=''):
        fake = Path(directory) / 'bin'
        fake.mkdir(exist_ok=True)
        # Like this router's logread: -f only follows NEW messages, no backlog.
        (fake / 'logread').write_text('#!/bin/sh\nif [ "${1:-}" = -f ]; then cat "$FOLLOW_FILE"; else cat "$LINES_FILE"; fi\n')
        (fake / 'logread').chmod(0o755)
        source = Path(directory) / 'lines'
        source.write_text(lines)
        (Path(directory) / 'follow').write_text(follow)
        mounts = Path(directory) / 'mounts'
        mounts.write_text('/dev/sda4 /mnt/data ext4 rw 0 0\n' if mounted else '')
        env = dict(os.environ, PATH=f'{fake}:{os.environ["PATH"]}', LINES_FILE=str(source), FOLLOW_FILE=str(Path(directory) / 'follow'),
                   BOOT_MARK=str(Path(directory) / 'boot-mark'),
                   LOG_DIR=str(Path(directory) / 'log'), MAX_BYTES=max_bytes, PROC_MOUNTS=str(mounts))
        return subprocess.run(['sh', str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10)

    def test_only_abnormal_events_are_kept_and_tailscale_noise_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_log(directory, LINES)
            self.assertEqual(result.returncode, 0, result.stderr)
            kept = (Path(directory) / 'log/error.log').read_text()
            self.assertIn('ntfs3(sda2)', kept)
            self.assertIn('Out of memory', kept)
            self.assertIn('watchcat', kept)
            for noise in ('tailscaled', 'cleared cache', 'ordinary note'):
                self.assertNotIn(noise, kept)

    def test_boot_backlog_is_written_once_then_new_events_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            later = 'Sun Nov  8 18:00:00 2026 daemon.err odhcpd[7]: later failure\n'
            self.assertEqual(self.run_log(directory, LINES, follow=later).returncode, 0)
            # A service restart in the same boot must not copy the backlog again.
            self.assertEqual(self.run_log(directory, LINES, follow=later).returncode, 0)
            kept = (Path(directory) / 'log/error.log').read_text()
            self.assertEqual(kept.count('Out of memory'), 1)
            self.assertEqual(kept.count('==== boot'), 1)
            self.assertEqual(kept.count('later failure'), 2)

    def test_file_is_rotated_instead_of_growing_without_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            lines = ''.join(f'Sun Nov  8 16:18:{i % 60:02d} 2026 kern.err kernel: failure {i}\n' for i in range(300))
            self.assertEqual(self.run_log(directory, lines, max_bytes='4096').returncode, 0)
            log = Path(directory) / 'log'
            self.assertLessEqual((log / 'error.log').stat().st_size, 4096 + 200)
            self.assertTrue((log / 'error.log.1').exists())
            self.assertFalse((log / 'error.log.2').exists())

    def test_nothing_is_written_when_the_data_partition_is_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_log(directory, LINES, mounted=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((Path(directory) / 'log').exists())

    def test_service_starts_at_boot(self):
        link = REPO / 'files/x86/etc/rc.d/S99error-log'
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), '../init.d/error-log')
        self.assertTrue(os.access(INIT, os.X_OK) and os.access(SCRIPT, os.X_OK))


if __name__ == '__main__':
    unittest.main()
