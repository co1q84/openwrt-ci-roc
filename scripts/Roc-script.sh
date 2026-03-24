# 修改默认IP、主机名与版本显示
sed -i 's/192.168.1.1/192.168.100.1/g' package/base-files/files/bin/config_generate
sed -i "s/hostname='.*'/hostname='Roc'/g" package/base-files/files/bin/config_generate
sed -i "s#_('Firmware Version'), (L\.isObject(boardinfo\.release) ? boardinfo\.release\.description + ' / ' : '') + (luciversion || ''),# \
            _('Firmware Version'),\n \
            E('span', {}, [\n \
                (L.isObject(boardinfo.release)\n \
                ? boardinfo.release.description + ' / '\n \
                : '') + (luciversion || '') + ' / ',\n \
            E('a', {\n \
                href: 'https://github.com/laipeng668/openwrt-ci-roc/releases',\n \
                target: '_blank',\n \
                rel: 'noopener noreferrer'\n \
                }, [ 'Built by Roc $(date "+%Y-%m-%d %H:%M:%S")' ])\n \
            ]),#" feeds/luci/modules/luci-mod-status/htdocs/luci-static/resources/view/status/include/10_system.js

# 清理与当前产品无关的第三方软件源
rm -rf feeds/luci/applications/luci-app-openclash
rm -rf feeds/luci/themes/luci-theme-argon
rm -rf feeds/luci/applications/luci-app-argon-config
rm -rf package/luci-app-lucky
rm -rf package/luci-app-openclash

# 引入 iStore feed
grep -q '^src-git istore ' feeds.conf.default || echo 'src-git istore https://github.com/linkease/istore;main' >> feeds.conf.default

# 保留当前需要的第三方软件
git clone --depth=1 https://github.com/jerrykuku/luci-theme-argon feeds/luci/themes/luci-theme-argon
git clone --depth=1 https://github.com/jerrykuku/luci-app-argon-config feeds/luci/applications/luci-app-argon-config
git clone --depth=1 https://github.com/gdy666/luci-app-lucky package/luci-app-lucky
git clone --depth=1 https://github.com/vernesong/OpenClash package/luci-app-openclash

# 通用低风险默认项
mkdir -p files/etc/uci-defaults
cat <<'EOF' > files/etc/uci-defaults/99-roc-defaults
#!/bin/sh

uci -q set system.@system[0].hostname='Roc'
uci -q set system.@system[0].timezone='CST-8'
uci -q set system.@system[0].zonename='Asia/Shanghai'
uci -q set luci.main.mediaurlbase='/luci-static/argon'
uci commit system
uci commit luci

exit 0
EOF
chmod 0755 files/etc/uci-defaults/99-roc-defaults

# 太乙: 仅在系统已存在 extroot 分区时迁移 overlay，避免首次启动自动改盘带来的风险
cat <<'EOF' > files/etc/uci-defaults/99-taiyi-extroot
#!/bin/sh

. /lib/functions/system.sh

BOARD="$(board_name 2>/dev/null)"
[ "$BOARD" = "jdcloud,re-cs-07" ] || exit 0
[ -b /dev/mmcblk0 ] || exit 0
command -v block >/dev/null 2>&1 || exit 0

if grep -q ' /overlay ext4 ' /proc/mounts; then
    exit 0
fi

LABEL="extroot"
DEVICE="$(blkid -L "${LABEL}" 2>/dev/null)"
[ -b "${DEVICE}" ] || exit 0

UUID="$(block info "${DEVICE}" | sed -n 's/.*UUID="\([^"]*\)".*/\1/p')"
MOUNT="$(block info | sed -n '/MOUNT=".*\/overlay"/s/.*MOUNT="\([^"]*\)".*/\1/p' | head -n1)"
ORIG="$(block info | sed -n '/MOUNT=".*\/overlay"/s/:.*$//p' | head -n1)"
[ -n "${UUID}" ] || exit 0
[ -n "${MOUNT}" ] || MOUNT="/overlay"

mkdir -p /mnt/extroot
mount "${DEVICE}" /mnt/extroot || exit 0
tar -C "${MOUNT}" -cpf - . | tar -C /mnt/extroot -xpf - || {
    umount /mnt/extroot
    exit 0
}
umount /mnt/extroot

uci -q set fstab.@global[0].anon_mount='0'
uci -q set fstab.@global[0].auto_mount='1'
uci -q set fstab.@global[0].auto_swap='1'
uci -q delete fstab.extroot
uci -q set fstab.extroot='mount'
uci -q set fstab.extroot.uuid="${UUID}"
uci -q set fstab.extroot.target="${MOUNT}"
uci -q set fstab.extroot.fstype='ext4'
uci -q set fstab.extroot.options='rw,noatime'
uci -q set fstab.extroot.enabled='1'
uci -q set fstab.extroot.enabled_fsck='1'

if [ -n "${ORIG}" ]; then
    uci -q delete fstab.rwm
    uci -q set fstab.rwm='mount'
    uci -q set fstab.rwm.device="${ORIG}"
    uci -q set fstab.rwm.target='/rwm'
    uci -q set fstab.rwm.enabled='1'
fi

uci commit fstab

sync
(sleep 3; reboot) &
exit 0
EOF
chmod 0755 files/etc/uci-defaults/99-taiyi-extroot

./scripts/feeds update -a
./scripts/feeds install -a
