import os
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import struct
import pty
from test_x86_build import load_build

SCRIPT = Path(__file__).resolve().parents[1] / 'files/x86/usr/sbin/roc-update'


class UpdateTests(unittest.TestCase):
    def test_build_stamp_recognizes_already_installed_release(self):
        build = load_build()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            self.assertTrue(hasattr(build, 'stamp_build'), 'firmware build identity is not stamped')
            build.stamp_build(source, {'source': {'commit': 'f'*40}}, 'x86-64-123-1')
            stamp = source / 'files/etc/roc-build.json'
            self.assertEqual(self.call('is_current_build "$1" "$2"', stamp, 'x86-64-123-1').returncode, 0)
            self.assertNotEqual(self.call('is_current_build "$1" "$2"', stamp, 'x86-64-124-1').returncode, 0)
            self.assertNotEqual(self.call('is_current_build "$1" "$2"', source/'absent', 'x86-64-123-1').returncode, 0)

    def call(self, expression, *args, input='', tty=False):
        self.assertTrue(SCRIPT.exists(), 'router updater has not been implemented')
        command = ['sh', '-c', '. "$1"; shift; ' + expression,
                   'test-shell', str(SCRIPT), *map(str, args)]
        if not tty:
            return subprocess.run(command, input=input, text=True, capture_output=True)
        master, slave = pty.openpty()
        try:
            return subprocess.run(command, stdin=slave, text=True, capture_output=True, timeout=10)
        finally:
            os.close(master)
            os.close(slave)

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
        entries = 'etc/openclash/core/clash_meta\netc/openclash/clash\netc/openclash/config/my profile.yaml\netc/openclash/custom/rules.list\netc/config/lucky.daji/cert.pem\netc/tailscale/tailscaled.state\netc/nikki/run/providers/rule/user.yaml\netc/nikki/run/config.yaml\netc/uci-defaults/10_disable_services\netc/apk/repositories.d/distfeeds.list\n'
        result = self.call('filter_backup', input=entries)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'etc/openclash/config/my profile.yaml\netc/openclash/custom/rules.list\netc/config/lucky.daji/cert.pem\netc/tailscale/tailscaled.state\netc/nikki/run/providers/rule/user.yaml\netc/uci-defaults/10_disable_services\n')

    def test_absent_or_wrong_confirmation_never_flashes(self):
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / 'flashed'
            expression = 'confirm_upgrade x86-64-123-1 && touch "$1"'
            for response in ['', 'yes\nyes\n', 'BACKUP-SAVED\nwrong\n']:
                result = self.call(expression, sentinel, input=response)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(sentinel.exists())

    def test_upgrade_libraries_allow_unset_openwrt_variables(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory)
            (library / 'upgrade').mkdir()
            (library / 'functions.sh').write_text('[ -n "$IPKG_INSTROOT" ] || :\n')
            (library / 'upgrade/common.sh').write_text('library_probe() { printf "library-ok"; }\n')
            result = self.call('openwrt_call "$1" library_probe; printf ":%s" "$-"', library)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.startswith('library-ok:'))
            self.assertIn('u', result.stdout.split(':')[1])

    def test_grub_reserved_partition_is_not_mistaken_for_extra_data(self):
        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / 'disk-header'
            header = bytearray(34*512)
            header[512:520] = b'EFI PART'
            header[1280:1296] = bytes.fromhex('4861682149646f6e744e656564454649')
            disk.write_bytes(header)
            table = '1 512 131072\n2 131584 1966080\n3 34 478\n4 3000000 10000\n'
            result = self.call('normalize_partitions "$1"', disk, input=table)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '1\t512\t131072\n2\t131584\t1966080\n4\t3000000\t10000\n')

    def test_preflight_failures_do_not_reach_flashing_command(self):
        for stage in ['prepare_image', 'make_backup', 'confirm_upgrade', 'read_device_layout', 'image-test']:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                sentinel = Path(directory) / 'flashed'
                expression = '''
                id() { printf 0; }
                apk() { :; }
                check_device() { :; }
                get_release() { TAG=x86-64-123-1; printf '{"image":{"sha256":"a"}}' > "$WORK/release.json"; }
                prepare_image() { IMAGE=$WORK/image; :; }
                make_backup() { BACKUP_SHA=a; :; }
                confirm_upgrade() { :; }
                read_device_layout() { :; }
                verify_asset() { :; }
                sysupgrade() { if [ "$1" = -T ]; then :; else touch "$FLASHED"; fi; }
                '''
                if stage == 'image-test':
                    expression += 'sysupgrade() { if [ "$1" = -T ]; then echo failure-stage >&2; return 1; else touch "$FLASHED"; fi; };\n'
                else:
                    expression += stage + '() { echo failure-stage >&2; return 1; };\n'
                expression += 'mktemp() { command mktemp -d "$TEST_TMP/roc-update.XXXXXX"; }; FLASHED=$1; TEST_TMP=$2; main upgrade'
                result = self.call(expression, sentinel, directory, tty=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('failure-stage', result.stderr)
                self.assertFalse(sentinel.exists())


if __name__ == '__main__':
    unittest.main()
