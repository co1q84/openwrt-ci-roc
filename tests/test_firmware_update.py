import hashlib
import os
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import struct
import pty
from test_x86_build import load_build

SCRIPT = Path(__file__).resolve().parents[1] / 'files/x86/usr/sbin/firmware-update'


class UpdateTests(unittest.TestCase):
    def test_build_stamp_recognizes_already_installed_release(self):
        build = load_build()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            self.assertTrue(hasattr(build, 'stamp_build'), 'firmware build identity is not stamped')
            build.stamp_build(source, {'source': {'commit': 'f'*40}}, 'x86-64-123-1')
            stamp = source / 'files/etc/firmware-build.json'
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
                              'partitions': [[1,512,131072],[2,131584,4194304]]}}
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

    def test_restored_config_archive_never_changes_system_directory_permissions(self):
        # Real failure: `tar -C dir .` under umask 077 stored "./" and "./etc/" as 0700;
        # restoring made / and /etc root-only, ubusd could not start, boot hung at "- ubus -".
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            setup = ('mkdir -p "$1/src/etc/config" "$1/src/etc/openclash/config" "$1/src/etc/tailscale" && '
                     'echo net > "$1/src/etc/config/network" && echo p > "$1/src/etc/openclash/config/我的 配置.yaml" && '
                     'echo s > "$1/src/etc/tailscale/tailscaled.state" && ln -s /usr/bin/mihomo "$1/src/etc/core" && ')
            result = self.call(setup + 'pack_config "$1/src" "$1/out.tar.gz"', root)
            self.assertEqual(result.returncode, 0, result.stderr)
            listing = subprocess.run(['tar', '-tvzf', root / 'out.tar.gz'], text=True, capture_output=True, check=True).stdout
            self.assertFalse([l for l in listing.splitlines() if l.startswith('d')], listing)
            names = sorted(subprocess.run(['tar', '-tzf', root / 'out.tar.gz'], text=True, capture_output=True,
                                          check=True).stdout.splitlines())
            self.assertEqual(names, ['etc/config/network', 'etc/core', 'etc/openclash/config/我的 配置.yaml',
                                     'etc/tailscale/tailscaled.state'])
            restored = root / 'restored'
            restored.mkdir(mode=0o755)
            subprocess.run(['tar', '-xzf', root / 'out.tar.gz', '-C', restored], check=True)
            self.assertEqual(restored.stat().st_mode & 0o777, 0o755)
            self.assertEqual((restored / 'etc/openclash/config/我的 配置.yaml').read_text(), 'p\n')
            self.assertEqual(os.readlink(restored / 'etc/core'), '/usr/bin/mihomo')

    def test_old_cores_and_removed_nikki_excluded_but_private_configs_retained(self):
        entries = 'etc/openclash/core/clash_meta\netc/openclash/clash\netc/openclash/config/my profile.yaml\netc/openclash/custom/rules.list\netc/config/lucky.daji/cert.pem\netc/tailscale/tailscaled.state\netc/nikki/run/providers/rule/user.yaml\netc/nikki/profiles/p.yaml\netc/config/nikki\netc/uci-defaults/10_disable_services\netc/apk/repositories.d/distfeeds.list\n'
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
        for stage in ['prepare_image', 'make_backup', 'confirm_upgrade', 'read_device_layout', 'image-test',
                      'check_boot_space', 'keep_rollback']:
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
                check_boot_space() { :; }
                keep_rollback() { :; }
                read_device_layout() { :; }
                verify_asset() { :; }
                sysupgrade() { if [ "$1" = -T ]; then :; else touch "$FLASHED"; fi; }
                '''
                if stage == 'image-test':
                    expression += 'sysupgrade() { if [ "$1" = -T ]; then echo failure-stage >&2; return 1; else touch "$FLASHED"; fi; };\n'
                else:
                    expression += stage + '() { echo failure-stage >&2; return 1; };\n'
                expression += 'mktemp() { command mktemp -d "$TEST_TMP/firmware-update.XXXXXX"; }; FLASHED=$1; TEST_TMP=$2; main upgrade'
                result = self.call(expression, sentinel, directory, tty=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('failure-stage', result.stderr)
                self.assertFalse(sentinel.exists())


    def test_layout_change_rewrites_only_a_disk_without_data_partition(self):
        # 960 -> 2048 MiB root: a USB-only disk is rewritten by sysupgrade with its
        # configuration kept; an SSD with a data partition would lose that partition.
        image = '1\t512\t131072\n2\t131584\t4194304\n'
        stub = 'openwrt_call() { cat "$DEVICE"; }; '
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / 'expected.partitions').write_text(image)
            (work / 'boot-device').write_text('sdb\n')
            device = work / 'device'
            cases = [('1\t512\t131072\n2\t131584\t1966080\n', True, '1'),     # old USB layout
                     (image, True, ''),                                              # same layout
                     ('1\t512\t131072\n2\t131584\t1966080\n4\t8388608\t1000\n', False, '')]  # SSD
            for layout, ok, change in cases:
                with self.subTest(layout=layout):
                    device.write_text(layout)
                    result = self.call(stub + 'WORK="$1"; DEVICE="$2"; LAYOUT_CHANGE=; check_layout && echo "change=$LAYOUT_CHANGE"',
                                       work, device)
                    self.assertEqual(result.returncode == 0, ok, result.stderr)
                    if ok:
                        self.assertIn(f'change={change}\n', result.stdout)
                    else:
                        self.assertIn('migrate', result.stderr)

    def test_system_partitions_must_end_before_the_ssd_data_partition(self):
        with tempfile.TemporaryDirectory() as directory:
            layout = Path(directory) / 'expected'
            for root, ok in [(4194304, True), (8257024, True), (8257025, False)]:
                with self.subTest(root=root):
                    layout.write_text(f'1\t512\t131072\n2\t131584\t{root}\n')
                    result = self.call('system_fits_before_data "$1"', layout)
                    self.assertEqual(result.returncode == 0, ok, result.stderr)

    def test_extra_data_partition_is_allowed_but_system_changes_are_not(self):
        expected = '1\t512\t131072\n2\t131584\t1966080\n'
        cases = {
            expected: True,
            expected + '4\t8388608\t491729551\n': True,             # SSD data partition
            '1\t512\t131072\n2\t131584\t3932160\n': False,           # root partition resized
            '2\t131584\t1966080\n4\t8388608\t1000\n': False,         # boot partition missing
            expected + '4\t2000000\t1000000\n': False,               # overlaps the root partition
            expected + '4\t100\t300\n': False,                       # overlaps reserved boot area
        }
        with tempfile.TemporaryDirectory() as directory:
            want = Path(directory) / 'expected'
            want.write_text(expected)
            have = Path(directory) / 'device'
            for layout, accepted in cases.items():
                with self.subTest(layout=layout):
                    have.write_text(layout)
                    result = self.call('layout_compatible "$1" "$2"', have, want)
                    self.assertEqual(result.returncode == 0, accepted, result.stderr)

    def target_env(self, directory, removable='0', mounted='', boot='sdb'):
        root = Path(directory)
        (root / 'sys/block/sda').mkdir(parents=True)
        (root / 'sys/block/sda/removable').write_text(removable + '\n')
        (root / 'sys/block/sda/size').write_text('500118192\n')
        (root / 'mounts').write_text(mounted)
        (root / 'swaps').write_text('Filename Type Size Used Priority\n')
        dev = root / 'dev'
        dev.mkdir()
        return ('SYSFS="$1/sys"; PROC_MOUNTS="$1/mounts"; PROC_SWAPS="$1/swaps"; '
                f'is_block() {{ [ "$1" = /dev/sda ]; }}; boot_disk() {{ echo {boot}; }}; ')

    def test_unsafe_migration_targets_are_refused(self):
        cases = [
            ({}, '/dev/sda', True),
            ({'boot': 'sda'}, '/dev/sda', False),                    # the running system disk
            ({'removable': '1'}, '/dev/sda', False),                 # a USB stick, not the SSD
            ({'mounted': '/dev/sda1 /mnt/sda1 ntfs3 rw 0 0\n'}, '/dev/sda', False),
            ({}, '/dev/sdz', False),                                 # not a block device
            ({}, '/dev/sda1', False),                                # a partition, not a disk
        ]
        for options, target, accepted in cases:
            with self.subTest(options=options, target=target), tempfile.TemporaryDirectory() as directory:
                setup = self.target_env(directory, **options)
                result = self.call(setup + 'check_target_disk "$2"', directory, target)
                self.assertEqual(result.returncode == 0, accepted, result.stderr)

    def test_migration_requires_exact_erase_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / 'written'
            for response in ['', 'yes\n', 'ERASE /dev/sdb\n', 'erase /dev/sda\n']:
                result = self.call('confirm_migration /dev/sda && touch "$1"', sentinel, input=response)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(sentinel.exists())
            result = self.call('confirm_migration /dev/sda && touch "$1"', sentinel, input='ERASE /dev/sda\n')
            self.assertEqual(result.returncode, 0, result.stderr)

    def gpt(self, path, root_guid):
        data = bytearray(4 * 512)
        data[512:520] = b'EFI PART'
        data[1024 + 128 + 16:1024 + 128 + 32] = bytes.fromhex(root_guid)
        path.write_bytes(data)

    def test_identical_root_partuuid_on_two_disks_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            image, disk = Path(directory) / 'image', Path(directory) / 'disk'
            self.gpt(image, '11'*16)
            self.gpt(disk, '22'*16)
            self.assertEqual(self.call('distinct_root_ids "$1" "$2"', image, disk).returncode, 0)
            self.gpt(disk, '11'*16)
            self.assertNotEqual(self.call('distinct_root_ids "$1" "$2"', image, disk).returncode, 0)

    def test_partition_device_names(self):
        result = self.call('partition_device /dev/sda 4; partition_device /dev/nvme0n1 4')
        self.assertEqual(result.stdout, '/dev/sda4\n/dev/nvme0n1p4\n')

    def test_migration_preflight_failures_never_write_the_disk(self):
        for stage in ['check_target_disk', 'prepare_image', 'make_backup', 'distinct_root_ids', 'confirm_migration']:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                sentinel = Path(directory) / 'written'
                expression = """
                id() { printf 0; }
                apk() { :; }; sysupgrade() { :; }; sgdisk() { :; }; partx() { :; }
                mkfs_ext4() { :; }; alias mkfs.ext4=mkfs_ext4; blkid() { :; }; uci() { :; }
                boot_disk() { echo sdb; }
                check_device() { :; }
                get_release() { TAG=x86-64-123-1; printf '{"image":{"sha256":"a","partitions":[]}}' > "$WORK/release.json"; }
                check_target_disk() { :; }
                prepare_image() { IMAGE=$WORK/image; :; }
                make_backup() { :; }
                distinct_root_ids() { :; }
                confirm_migration() { :; }
                image_header() { :; }
                verify_asset() { :; }
                write_target() { touch "$WRITTEN"; }
                """
                expression += stage + '() { echo failure-stage >&2; return 1; };\n'
                expression += 'mktemp() { command mktemp -d "$TEST_TMP/fw.XXXXXX"; }; WRITTEN=$1; TEST_TMP=$2; main migrate /dev/sda'
                result = self.call(expression, sentinel, directory, tty=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('failure-stage', result.stderr)
                self.assertFalse(sentinel.exists())


    def fake_curl(self, directory, proxy_ok=True):
        # Records argv and the -K stdin config; the proxied attempt can fail.
        root = Path(directory)
        fake = root / 'bin'
        fake.mkdir(exist_ok=True)
        (fake / 'curl').write_text(
            '#!/bin/sh\n'
            'config=$(cat 2>/dev/null)\n'
            'printf "ARGS %s\\nCONF %s\\n" "$*" "$config" >> "$LOG"\n'
            'case "$*" in *127.0.0.1*) [ "$PROXY_OK" = 1 ] || exit 7;; esac\n'
            'while [ $# -gt 0 ]; do [ "$1" = -o ] && printf payload > "$2"; shift; done\n')
        (fake / 'curl').chmod(0o755)
        (fake / 'uci').write_text(
            '#!/bin/sh\n'
            'case "$*" in\n'
            '  *config.mixed_port*) echo 7893;;\n'
            '  *authentication*enabled*) echo 1;;\n'
            '  *authentication*username*) echo Clash;;\n'
            '  *authentication*password*) echo s3cret-value;;\n'
            '  *) exit 1;;\n'
            'esac\n')
        (fake / 'uci').chmod(0o755)
        log = root / 'log'
        env = (f'export PATH="{fake}:$PATH" LOG="{log}" PROXY_OK={1 if proxy_ok else 0}; '
               'proxy_listening() { :; }; ')
        return env, log

    def test_downloads_prefer_local_openclash_without_exposing_its_password(self):
        with tempfile.TemporaryDirectory() as directory:
            env, log = self.fake_curl(directory)
            out = Path(directory) / 'file'
            result = self.call(env + 'download "$1" "$2"', 'https://api.github.com/x', out)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(out.read_text(), 'payload')
            text = log.read_text()
            self.assertIn('127.0.0.1:7893', text)
            args = '\n'.join(l for l in text.splitlines() if l.startswith('ARGS'))
            self.assertNotIn('s3cret-value', args)            # never on the command line
            self.assertIn('s3cret-value', text)                # passed via curl config on stdin
            self.assertNotIn('s3cret-value', result.stdout + result.stderr)

    def test_failed_proxy_falls_back_to_direct(self):
        with tempfile.TemporaryDirectory() as directory:
            env, log = self.fake_curl(directory, proxy_ok=False)
            out = Path(directory) / 'file'
            result = self.call(env + 'download "$1" "$2"', 'https://api.github.com/x', out)
            self.assertEqual(result.returncode, 0, result.stderr)
            attempts = [l for l in log.read_text().splitlines() if l.startswith('ARGS')]
            self.assertEqual(len(attempts), 2)
            self.assertIn('127.0.0.1', attempts[0])
            self.assertNotIn('127.0.0.1', attempts[1])

    def test_release_assets_use_the_api_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            releases = Path(directory) / 'releases.json'
            releases.write_text(json.dumps([{'tag_name': 'x86-64-1-1', 'assets': [
                {'name': 'release.json', 'url': 'https://api.github.com/repos/o/r/releases/assets/7'}]}]))
            ok = self.call('WORK="$1"; TAG=x86-64-1-1; asset_url release.json', directory)
            self.assertEqual(ok.stdout.strip(), 'https://api.github.com/repos/o/r/releases/assets/7')
            missing = self.call('WORK="$1"; TAG=x86-64-1-1; asset_url image.gz', directory)
            self.assertNotEqual(missing.returncode, 0)

    ROLLBACK_STUBS = """
    id() { printf 0; }
    interactive() { :; }
    apk() { :; }; uci() { :; }
    check_device() { :; }; check_layout() { :; }; check_boot_space() { :; }
    data_mounted() { :; }
    current_tag() { echo x86-64-2-1; }
    image_partitions() { :; }
    make_backup() { mkdir -p "$WORK/migration"; echo cfg > "$WORK/migration-backup.tar.gz"; }
    sysupgrade() { if [ "$1" = -T ]; then :; else echo "$*" > "$FLASHED"; fi; }
    mktemp() { command mktemp -d "$TEST_TMP/fw.XXXXXX"; }
    """

    def rollback_store(self, directory, sha_ok=True):
        store = Path(directory) / 'store'
        prev = store / 'x86-64-1-1'
        prev.mkdir(parents=True)
        (prev / 'image.img.gz').write_bytes(b'old image')
        digest = hashlib.sha256(b'old image').hexdigest() if sha_ok else 'f' * 64
        (prev / 'image.sha256').write_text(digest + '\n')
        (prev / 'config.tar.gz').write_bytes(b'cfg')
        (store / 'previous').write_text('x86-64-1-1\n')
        return store

    def run_rollback(self, directory, store, answer):
        flashed = Path(directory) / 'flashed'
        expression = (self.ROLLBACK_STUBS + 'gzip() { :; }; STORE="$3"; FLASHED=$1; TEST_TMP=$2; '
                      'printf "%s\\n" "$4" > "$TEST_TMP/answer"; main rollback < "$TEST_TMP/answer"')
        result = self.call(expression, flashed, directory, store, answer, tty=False)
        return result, flashed

    def test_rollback_flashes_previous_image_with_its_saved_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.rollback_store(directory)
            result, flashed = self.run_rollback(directory, store, 'ROLLBACK x86-64-1-1')
            self.assertEqual(result.returncode, 0, result.stderr)
            args = flashed.read_text()
            self.assertIn(str(store / 'x86-64-1-1/config.tar.gz'), args)
            self.assertIn(str(store / 'x86-64-1-1/image.img.gz'), args)
            # The firmware being left becomes the next rollback target.
            self.assertEqual((store / 'previous').read_text().strip(), 'x86-64-2-1')
            self.assertTrue((store / 'x86-64-2-1/config.tar.gz').exists())

    def test_rollback_refuses_tampered_image_wrong_answer_or_no_target(self):
        cases = [('tampered', False, 'ROLLBACK x86-64-1-1'), ('answer', True, 'yes'), ('none', True, 'ROLLBACK x86-64-1-1')]
        for name, sha_ok, answer in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                store = self.rollback_store(directory, sha_ok)
                if name == 'none':
                    (store / 'previous').unlink()
                result, flashed = self.run_rollback(directory, store, answer)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(flashed.exists())

    def test_upgrade_keeps_a_rollback_point_and_prunes_older_ones(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / 'store'
            (store / 'x86-64-0-1').mkdir(parents=True)          # older than the previous: pruned
            (store / 'x86-64-2-1').mkdir()
            (store / 'x86-64-2-1/image.img.gz').write_bytes(b'current')
            image = Path(directory) / 'new.img.gz'
            image.write_bytes(b'new image')
            work = Path(directory) / 'work'
            (work / 'migration/etc/config').mkdir(parents=True)
            (work / 'migration/etc/config/network').write_text('cfg\n')
            expression = (self.ROLLBACK_STUBS + 'write_expectations() { :; }; '
                          'STORE="$1"; WORK="$2"; IMAGE="$3"; TAG=x86-64-3-1; keep_rollback')
            result = self.call(expression, store, work, image)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((store / 'previous').read_text().strip(), 'x86-64-2-1')
            self.assertTrue((store / 'x86-64-2-1/config.tar.gz').exists())
            self.assertEqual((store / 'x86-64-3-1/image.img.gz').read_bytes(), b'new image')
            self.assertEqual((store / 'x86-64-3-1/image.sha256').read_text().split()[0],
                             hashlib.sha256(b'new image').hexdigest())
            self.assertFalse((store / 'x86-64-0-1').exists())

if __name__ == '__main__':
    unittest.main()
