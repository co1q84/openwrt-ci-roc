import os
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'files/x86/usr/sbin/roc-update'


class UpdateTests(unittest.TestCase):
    def call(self, expression, *args, input=''):
        self.assertTrue(SCRIPT.exists(), 'router updater has not been implemented')
        return subprocess.run(['sh', '-c', '. "$1"; shift; ' + expression,
                               'test-shell', str(SCRIPT), *map(str, args)],
                              input=input, text=True, capture_output=True)

    def test_tampered_image_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'firmware'
            image.write_bytes(b'firmware')
            sha = 'c3bf47ea1f4a4a605470313cacb3a44f4a461f68c6faeab07e737610cb5ac835'
            self.assertEqual(self.call('verify_asset "$1" "$2"', image, sha).returncode, 0)
            image.write_bytes(b'changed firmware')
            self.assertNotEqual(self.call('verify_asset "$1" "$2"', image, sha).returncode, 0)

    def test_wrong_device_or_ext4_metadata_rejected(self):
        metadata = {'schema': 1, 'repository': 'co1q84/openwrt-ci-roc', 'tag': 'x86-64-123-1',
                    'target': 'x86/64', 'device': 'J4125-4L',
                    'image': {'name': 'immortalwrt-x86-64-generic-squashfs-combined-efi.img.gz',
                              'sha256': 'a'*64, 'size': 1024, 'filesystem': 'squashfs', 'boot': 'efi',
                              'partitions': [[1,512,131072],[2,131584,1966080]]}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'release.json'
            path.write_text(json.dumps(metadata))
            self.assertEqual(self.call('validate_metadata "$1"', path).returncode, 0)
            for key, value in [('device', 'another-router'), ('target', 'aarch64')]:
                bad = dict(metadata, **{key: value})
                path.write_text(json.dumps(bad))
                self.assertNotEqual(self.call('validate_metadata "$1"', path).returncode, 0)
            metadata['image']['filesystem'] = 'ext4'
            path.write_text(json.dumps(metadata))
            self.assertNotEqual(self.call('validate_metadata "$1"', path).returncode, 0)

    def test_core_executable_excluded_but_private_configs_retained(self):
        entries = 'etc/openclash/core/clash_meta\netc/openclash/clash\netc/openclash/config/my profile.yaml\netc/openclash/custom/rules.list\netc/config/lucky.daji/cert.pem\netc/tailscale/tailscaled.state\netc/uci-defaults/10_disable_services\netc/apk/repositories.d/distfeeds.list\n'
        result = self.call('filter_backup', input=entries)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'etc/openclash/config/my profile.yaml\netc/openclash/custom/rules.list\netc/config/lucky.daji/cert.pem\netc/tailscale/tailscaled.state\netc/uci-defaults/10_disable_services\n')

    def test_absent_or_wrong_confirmation_never_flashes(self):
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / 'flashed'
            expression = 'confirm_upgrade x86-64-123-1 && touch "$1"'
            for response in ['', 'yes\nyes\n', 'BACKUP-SAVED\nwrong\n']:
                result = self.call(expression, sentinel, input=response)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(sentinel.exists())


if __name__ == '__main__':
    unittest.main()
