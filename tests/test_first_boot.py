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


ROUTER = REPO / 'files/x86/etc/uci-defaults/83-x86-router-defaults'


class RouterDefaultsTests(unittest.TestCase):
    def run_defaults(self, directory, marker='', zone_networks='wan wan6', pings=0):
        root = Path(directory)
        calls = root / 'calls'
        bin_dir = root / 'bin'
        bin_dir.mkdir()
        (bin_dir / 'uci').write_text(
            '#!/bin/sh\necho "uci $*" >> "$CALLS"\ncase "$*" in\n'
            '  "-q get system.x86_defaults.router") [ -n "$MARKER" ] && echo "$MARKER";;\n'
            '  "-q get firewall.@zone[0].name") echo lan;;\n'
            '  "-q get firewall.@zone[1].name") echo wan;;\n'
            '  "-q get firewall.@zone[1].network") echo "$ZONE_NETWORKS";;\n'
            '  "-q get watchcat.@watchcat[0].mode") [ "$PINGS" -ge 1 ] && echo ping_reboot || exit 1;;\n'
            '  "-q get watchcat.@watchcat[1].mode") exit 1;;\n'
            '  "-q get firewall.@zone[2].name") exit 1;;\n'
            '  *" get "*) exit 1;;\nesac\nexit 0\n')
        (bin_dir / 'uci').chmod(0o755)
        env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}', CALLS=str(calls), MARKER=marker,
                   ZONE_NETWORKS=zone_networks, PINGS=str(pings), WATCHCAT_CONF=str(root / 'watchcat'))
        result = subprocess.run(['sh', str(ROUTER)], env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return calls.read_text() if calls.exists() else ''

    def test_fresh_install_gets_router_only_ipv6_and_wan_redial(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = self.run_defaults(directory, pings=1)
            for expected in ['set network.wan.ipv6=1', 'set network.wan6.device=@wan', 'set network.wan6.disabled=0',
                             'delete network.lan.ip6assign', 'set dhcp.lan.ra=disabled', 'set dhcp.lan.dhcpv6=disabled',
                             'set dhcp.lan.ndp=disabled', 'set dhcp.@dnsmasq[0].filter_aaaa=1',
                             'set watchcat.wan_redial.mode=run_script', 'set watchcat.wan_redial.period=10m',
                             "set watchcat.wan_redial.pinghosts=223.5.5.5 119.29.29.29",
                             'set watchcat.wan_redial.script=/usr/libexec/wan-redial',
                             "set watchcat.@watchcat[0].pinghosts=223.5.5.5 119.29.29.29",
                             'set system.x86_defaults.router=1']:
                self.assertIn(expected, calls)

    def test_settings_already_applied_are_never_reapplied(self):
        # The upgrade/migrate path writes the same marker; later user changes must stay.
        with tempfile.TemporaryDirectory() as directory:
            calls = self.run_defaults(directory, marker='1')
            self.assertEqual([l for l in calls.splitlines() if ' set ' in l or ' delete ' in l], [])

    def test_without_wan6_in_the_wan_zone_ipv6_stays_off_but_redial_is_set(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = self.run_defaults(directory, zone_networks='wan')
            self.assertNotIn('set network.wan6', calls)
            self.assertNotIn('set dhcp.lan.ra', calls)
            self.assertIn('set watchcat.wan_redial.mode=run_script', calls)
            self.assertIn('set system.x86_defaults.router=1', calls)


if __name__ == '__main__':
    unittest.main()
