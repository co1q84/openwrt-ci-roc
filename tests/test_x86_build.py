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
    def test_openclash_core_provider_survives_nikki_removal(self):
        build = load_build()
        required = build.required_config(REPO)
        # install_overlay links OpenClash's core to /usr/bin/mihomo from mihomo-meta.
        self.assertEqual(required.get('CONFIG_PACKAGE_mihomo-meta'), 'y')
        self.assertEqual(required.get('CONFIG_PACKAGE_luci-app-openclash'), 'y')
        self.assertNotEqual(required.get('CONFIG_PACKAGE_nikki', 'n'), 'y')

    def test_x86_removals_do_not_change_shared_taiyi_selections(self):
        build = load_build()
        shared = build.config_values(REPO / 'configs/General.config')
        x86 = build.required_config(REPO)
        for name in ('luci-app-samba4', 'luci-app-acme', 'luci-app-banip', 'luci-app-homeproxy',
                     'luci-app-store', 'luci-app-dufs', 'luci-app-filebrowser-go'):
            self.assertEqual(shared.get(f'CONFIG_PACKAGE_{name}'), 'y')
            self.assertEqual(x86.get(f'CONFIG_PACKAGE_{name}'), 'n')

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


    def test_conditional_theme_selection_stays_valid_shell(self):
        build = load_build()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            config = source / 'package/base-files/files/bin/config_generate'
            config.parent.mkdir(parents=True)
            config.write_text("hostname='ImmortalWrt'\n")
            # Vantage selects itself inside an if-block; dropping the line leaves "then fi".
            theme = source / 'package/roc/vantage/luci-theme-vantage/root/etc/uci-defaults/30_luci-theme-vantage'
            theme.parent.mkdir(parents=True)
            theme.write_text('uci -q set luci.themes.Vantage=/luci-static/vantage || exit 1\n'
                             'if [ "$PKG_UPGRADE" != 1 ]; then\n'
                             '\tuci -q set luci.main.mediaurlbase=/luci-static/vantage\n'
                             'fi\nuci -q commit luci\n')
            fake = source / 'bin'
            fake.mkdir()
            calls = source / 'calls'
            uci = fake / 'uci'
            uci.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n')
            uci.chmod(0o755)
            build.install_overlay(source, REPO)
            result = subprocess.run(['sh', str(theme)], capture_output=True, text=True,
                                    env=dict(os.environ, PATH=str(fake)+':'+os.environ['PATH'], CALLS=str(calls)))
            self.assertEqual(result.returncode, 0, result.stderr)
            log = calls.read_text()
            self.assertIn('luci.themes.Vantage=/luci-static/vantage', log)
            self.assertNotIn('mediaurlbase', log)


    def run_board_network(self, script, board):
        stub = ('board_config_update() { :; }; board_config_flush() { :; }\n'
                f'board_name() {{ echo {board}; }}\n'
                'ucidef_set_interfaces_lan_wan() { echo "lan=$1 wan=$2"; }\n'
                'ucidef_set_interface_lan() { echo "lan=$1"; }\n')
        body = script.read_text().replace('. /lib/functions/system.sh\n', '').replace(
            '. /lib/functions/uci-defaults.sh\n', stub)
        return subprocess.run(['sh', '-c', body], capture_output=True, text=True)

    def test_j4125_factory_ports_match_router_and_other_boards_unchanged(self):
        build = load_build()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            script = source / 'target/linux/x86/base-files/etc/board.d/02_network'
            script.parent.mkdir(parents=True)
            script.write_text('. /lib/functions/system.sh\n. /lib/functions/uci-defaults.sh\n'
                              'board_config_update\n\ncase "$(board_name)" in\n'
                              'supermicro-sys-e302-9d)\n\tucidef_set_interface_lan "eth0 eth1"\n\t;;\n'
                              'esac\nboard_config_flush\nexit 0\n')
            build.set_board_ports(source)
            result = self.run_board_network(script, 'cnction-j4125-4l')
            self.assertEqual((result.returncode, result.stdout), (0, 'lan=eth1 eth2 eth3 wan=eth0\n'), result.stderr)
            self.assertEqual(self.run_board_network(script, 'supermicro-sys-e302-9d').stdout, 'lan=eth0 eth1\n')
            self.assertEqual(self.run_board_network(script, 'other-board').stdout, '')
            build.set_board_ports(source)  # a rerun must not add a second entry
            self.assertEqual(script.read_text().count('cnction-j4125-4l)'), 1)
            script.write_text('upstream rewrote this file\n')
            with self.assertRaisesRegex(ValueError, 'board'):
                build.set_board_ports(source)


if __name__ == '__main__':
    unittest.main()
