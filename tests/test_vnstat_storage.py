import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'files/x86/usr/libexec/vnstat-storage'
STOCK = ('# vnStat config\n;DatabaseDir "/var/lib/vnstat"\nUpdateInterval 20\n'
         '\n# SSD data partition: history survives reboots and upgrades.\nDatabaseDir "/mnt/data/vnstat"\n')


class VnstatStorageTests(unittest.TestCase):
    def run_script(self, directory, mounted):
        conf = Path(directory) / 'vnstat.conf'
        mounts = Path(directory) / 'mounts'
        mounts.write_text('/dev/sda4 /mnt/data ext4 rw 0 0\n' if mounted else '/dev/loop0 /overlay f2fs rw 0 0\n')
        env = dict(os.environ, VNSTAT_CONF=str(conf), PROC_MOUNTS=str(mounts))
        result = subprocess.run(['sh', str(SCRIPT)], env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return conf.read_text()

    def active(self, text):
        return [l for l in text.splitlines() if l and not l.lstrip().startswith(('#', ';'))]

    def test_usb_only_keeps_history_on_the_system_disk_with_hourly_saves(self):
        # Real failure: without the SSD, /mnt/data/vnstat was created on the USB
        # overlay and written every 5 minutes.
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'vnstat.conf').write_text(STOCK)
            text = self.run_script(directory, mounted=False)
            self.assertEqual(self.active(text), ['UpdateInterval 20', 'DatabaseDir "/etc/vnstat"',
                                                 'SaveInterval 60', 'OfflineSaveInterval 60'])

    def test_ssd_keeps_history_on_the_data_partition_with_default_saves(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'vnstat.conf').write_text(STOCK)
            text = self.run_script(directory, mounted=True)
            self.assertEqual(self.active(text), ['UpdateInterval 20', 'DatabaseDir "/mnt/data/vnstat"',
                                                 'SaveInterval 5', 'OfflineSaveInterval 30'])

    def test_first_ssd_boot_carries_usb_history_over_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'vnstat.conf').write_text(STOCK)
            system, data = root / 'etc-vnstat', root / 'data'
            system.mkdir(); data.mkdir()
            (system / 'vnstat.db').write_text('usb history')
            (root / 'mounts').write_text(f'/dev/sda4 {data} ext4 rw 0 0\n')
            env = dict(os.environ, VNSTAT_CONF=str(root / 'vnstat.conf'), PROC_MOUNTS=str(root / 'mounts'),
                       MOUNT=str(data), SYSTEM_DIR=str(system))
            subprocess.run(['sh', str(SCRIPT)], env=env, check=True)
            self.assertEqual((data / 'vnstat/vnstat.db').read_text(), 'usb history')
            (data / 'vnstat/vnstat.db').write_text('ssd history')
            subprocess.run(['sh', str(SCRIPT)], env=env, check=True)
            self.assertEqual((data / 'vnstat/vnstat.db').read_text(), 'ssd history')

    def test_switching_modes_is_stable_and_unchanged_config_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            conf = Path(directory) / 'vnstat.conf'
            conf.write_text(STOCK)
            first = self.run_script(directory, mounted=False)
            self.run_script(directory, mounted=True)
            self.assertEqual(self.run_script(directory, mounted=False), first)
            inode = conf.stat().st_ino
            os.utime(conf, (1, 1))
            self.run_script(directory, mounted=False)
            self.assertEqual((conf.stat().st_ino, conf.stat().st_mtime), (inode, 1))


if __name__ == '__main__':
    unittest.main()
