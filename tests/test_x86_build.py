import importlib.util
from pathlib import Path
import tempfile
import unittest
import subprocess
import os
import json
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]


def load_build():
    path = REPO / 'scripts/x86-build.py'
    if not path.exists():
        raise AssertionError('x86 validation and preparation are not implemented')
    spec = importlib.util.spec_from_file_location('x86_build', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConfigurationTests(unittest.TestCase):
    def prepare_legacy_feed(self, source, source_version, mirror_hash):
        build = load_build()
        generate = source / 'package/base-files/files/bin/config_generate'
        generate.parent.mkdir(parents=True)
        generate.write_text("hostname='ImmortalWrt'\n")
        feed = source / 'feeds/helloworld'
        feed.mkdir(parents=True)
        (source / 'feeds/helloworld.index').write_text('Source-Makefile: shadowsocks-libev/Makefile\n')
        makefile = feed / 'shadowsocks-libev/Makefile'
        makefile.parent.mkdir()
        makefile.write_text(
            'PKG_NAME:=shadowsocks-libev\nPKG_VERSION:=3.3.5\n'
            'PKG_SOURCE_PROTO:=git\n'
            'PKG_SOURCE_URL:=https://github.com/shadowsocks/shadowsocks-libev.git\n'
            f'PKG_SOURCE_VERSION:={source_version}\n'
            f'PKG_MIRROR_HASH:={mirror_hash}\n')
        feeds = source / 'scripts/feeds'
        feeds.parent.mkdir()
        feeds.write_text('#!/bin/sh\nexit 0\n')
        feeds.chmod(0o755)
        entry = {'url': 'https://github.com/fixture/source.git', 'commit': 'a'*40}
        lock = {'source': entry, 'feeds': {'helloworld': dict(entry)}, 'extras': {}}
        # Only GitHub resolution and network checkouts are replaced. Preparation,
        # feed commands, configuration, overlay and the emitted lock all run.
        with patch.object(build, 'resolve_sources', return_value=lock), patch.object(build, 'checkout'):
            build.prepare(source, REPO)
        return makefile, json.loads((source / 'sources.lock.json').read_text())

    def test_prepared_feed_accepts_the_verified_legacy_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            makefile, lock = self.prepare_legacy_feed(
                Path(directory), '9afa3cacf947f910be46b69fc5a7a1fdd02fd5e6',
                'b3898ad0a557bc8b0bbb2f3888101d461944239b0b7d4d4c6f164d73694a4595')
            # Independently reproduced by the Ubuntu builder from this exact Git
            # commit and its three pinned submodules, not from the patched code.
            archive_digest = '9d2293f16629d1e30ede304ccddbaaa4e922c1c5e7ea04cef0e9d274aafa6109'
            values = dict(line.split(':=', 1) for line in makefile.read_text().splitlines())
            self.assertEqual(values['PKG_MIRROR_HASH'], archive_digest)
            self.assertEqual(lock['source_fixes'][0]['mirror_hash_after'], archive_digest)

    def test_new_upstream_sources_or_hashes_are_not_overwritten(self):
        old_hash = 'b3898ad0a557bc8b0bbb2f3888101d461944239b0b7d4d4c6f164d73694a4595'
        for version, digest in [('b'*40, old_hash),
                                ('9afa3cacf947f910be46b69fc5a7a1fdd02fd5e6', 'c'*64)]:
            with self.subTest(version=version, digest=digest), tempfile.TemporaryDirectory() as directory:
                makefile, lock = self.prepare_legacy_feed(Path(directory), version, digest)
                values = dict(line.split(':=', 1) for line in makefile.read_text().splitlines())
                self.assertEqual(values['PKG_SOURCE_VERSION'], version)
                self.assertEqual(values['PKG_MIRROR_HASH'], digest)
                self.assertFalse(lock.get('source_fixes'))

    def test_next_build_resolves_new_upstream_commit(self):
        build = load_build()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()
            git('init', '-q')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            (source / 'version').write_text('1')
            git('add', '.')
            git('commit', '-qm', 'first release')
            first = build.resolve_ref(str(source), 'HEAD')
            (source / 'version').write_text('2')
            git('commit', '-qam', 'updated release')
            second = build.resolve_ref(str(source), 'HEAD')
            self.assertNotEqual(first, second)
            self.assertEqual(second, git('rev-parse', 'HEAD'))

    def test_missing_plugin_and_wrong_layout_are_rejected(self):
        build = load_build()
        required = {'CONFIG_PACKAGE_kmod-igc': 'y',
                    'CONFIG_PACKAGE_luci-app-openclash': 'y',
                    'CONFIG_TARGET_ROOTFS_PARTSIZE': '960',
                    'CONFIG_TARGET_ROOTFS_SQUASHFS': 'y'}
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / '.config'
            config.write_text('CONFIG_PACKAGE_kmod-igc=y\nCONFIG_TARGET_ROOTFS_PARTSIZE=1536\n')
            with self.assertRaisesRegex(ValueError, 'luci-app-openclash'):
                build.check_config(config, required)
            config.write_text('\n'.join(f'{k}={v}' for k, v in required.items()) + '\n')
            build.check_config(config, required)
            config.write_text(config.read_text().replace('960', '1536'))
            with self.assertRaisesRegex(ValueError, 'ROOTFS_PARTSIZE'):
                build.check_config(config, required)

    def test_source_lock_rejects_moving_branch(self):
        build = load_build()
        with self.assertRaisesRegex(ValueError, 'commit'):
            build.validate_lock({'source': {'url': 'https://github.com/immortalwrt/immortalwrt.git',
                                             'commit': 'master'}, 'feeds': {}, 'extras': {}})

    def test_restored_defaults_are_not_replaced(self):
        build = load_build()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            config = source / 'package/base-files/files/bin/config_generate'
            config.parent.mkdir(parents=True)
            config.write_text("hostname='ImmortalWrt'\n192.168.1.1\n")
            build.install_overlay(source, REPO)
            self.assertIn("hostname='OpenWrt'", config.read_text())
            self.assertIn('192.168.100.1', config.read_text())
            defaults = source / 'files/etc/uci-defaults/99-roc-defaults'
            # A restored /etc/config is authoritative. No post-restore rewrite exists.
            self.assertFalse(defaults.exists())
            self.assertFalse((source / 'files/etc/config/network').exists())
            self.assertFalse((source / 'files/etc/config/dropbear').exists())

    def test_new_theme_registration_keeps_existing_theme_selection(self):
        build = load_build()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            config = source / 'package/base-files/files/bin/config_generate'
            config.parent.mkdir(parents=True)
            config.write_text("hostname='ImmortalWrt'\n")
            theme = source / 'feeds/luci/themes/luci-theme-argon/root/etc/uci-defaults/30_luci-theme-argon'
            theme.parent.mkdir(parents=True)
            theme.write_text('uci batch <<EOF\nset luci.themes.Argon=/luci-static/argon\nset luci.main.mediaurlbase=/luci-static/argon\nEOF\n')
            fake = source / 'bin'
            fake.mkdir()
            selected = source / 'selected-theme'
            selected.write_text('/luci-static/aurora')
            uci = fake / 'uci'
            uci.write_text('#!/bin/sh\nwhile read -r line; do case "$line" in "set luci.main.mediaurlbase="*) printf "%s" "${line#*=}" > "$SELECTED";; esac; done\n')
            uci.chmod(0o755)
            build.install_overlay(source, REPO)
            subprocess.run(['sh', str(theme)], check=True,
                           env=dict(os.environ, PATH=str(fake)+':'+os.environ['PATH'], SELECTED=str(selected)))
            self.assertEqual(selected.read_text(), '/luci-static/aurora')


if __name__ == '__main__':
    unittest.main()
