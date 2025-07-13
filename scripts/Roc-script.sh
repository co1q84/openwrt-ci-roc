# 修改默认IP & 固件名称 & 编译署名
# sed -i 's/192.168.1.1/192.168.2.1/g' package/base-files/files/bin/config_generate
# sed -i "s/hostname='.*'/hostname='Roc'/g" package/base-files/files/bin/config_generate
# sed -i "s/(\(luciversion || ''\))/(\1) + (' \/ Built by Roc')/g" feeds/luci/modules/luci-mod-status/htdocs/luci-static/resources/view/status/include/10_system.js

# 修改太乙启动LED为绿色，运行LED为蓝色(VIKINGYFY项目)
sed -i 's/boot/roc/g; s/running/boot/g; s/roc/running/g' target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq6010-re-cs-07.dts

# 修正使用ccache编译vlmcsd的问题
mkdir -p feeds/packages/net/vlmcsd/patches
cp -f $GITHUB_WORKSPACE/patches/fix_vlmcsd_compile_with_ccache.patch feeds/packages/net/vlmcsd/patches

# 移除要替换的包
rm -rf feeds/packages/net/alist
rm -rf feeds/luci/applications/luci-app-alist
rm -rf feeds/luci/themes/luci-theme-argon
rm -rf feeds/luci/themes/luci-theme-netgear
rm -rf feeds/packages/net/open-app-filter

rm -rf feeds/packages/net/adguardhome
rm -rf feeds/packages/net/openlist
rm -rf feeds/luci/applications/luci-app-openlist

# Git稀疏克隆，只克隆指定目录到本地
function git_sparse_clone() {
  branch="$1" repourl="$2" && shift 2
  git clone --depth=1 -b $branch --single-branch --filter=blob:none --sparse $repourl
  repodir=$(echo $repourl | awk -F '/' '{print $(NF)}')
  cd $repodir && git sparse-checkout set $@
  mv -f $@ ../package
  cd .. && rm -rf $repodir
}

# OpenList & AdGuardHome & WolPlus & Lucky & OpenAppFilter & 集客无线AC控制器 & 雅典娜LED控制
git clone --depth=1 https://github.com/sbwml/luci-app-openlist package/openlist
git_sparse_clone master https://github.com/kenzok8/openwrt-packages adguardhome luci-app-adguardhome
git_sparse_clone main https://github.com/VIKINGYFY/packages luci-app-wolplus
git clone --depth=1 https://github.com/gdy666/luci-app-lucky package/luci-app-lucky
git clone --depth=1 https://github.com/destan19/OpenAppFilter.git package/OpenAppFilter
git clone --depth=1 https://github.com/lwb1978/openwrt-gecoosac package/openwrt-gecoosac
git clone --depth=1 https://github.com/NONGFAH/luci-app-athena-led package/luci-app-athena-led
chmod +x package/luci-app-athena-led/root/etc/init.d/athena_led package/luci-app-athena-led/root/usr/sbin/athena-led
git_sparse_clone master https://github.com/vernesong/OpenClash luci-app-openclash
chmod +x package/luci-app-athena-led/root/etc/init.d/athena_led
chmod +x package/luci-app-athena-led/root/usr/sbin/athena-led
# rm -rf package/luci-app-athena-led/luasrc/view/athena_led/athena_led_gift.htm
# sed -i '/entry({ "admin", "system", "athena_led", "gift" }, template("athena_led\/athena_led_gift"), _("Gift"), 2)/d' package/luci-app-athena-led/luasrc/controller/athena_led.lua
git clone --depth=1 https://github.com/sbwml/packages_lang_golang -b 23.x feeds/packages/lang/golang
chmod +x package/luci-app-athena-led/root/etc/init.d/athena_led package/luci-app-athena-led/root/usr/sbin/athena-led

# Themes
git clone --depth=1 -b 18.06 https://github.com/kiddin9/luci-theme-edge package/luci-theme-edge
git clone --depth=1 -b 18.06 https://github.com/jerrykuku/luci-theme-argon package/luci-theme-argon
git clone --depth=1 https://github.com/jerrykuku/luci-app-argon-config package/luci-app-argon-config
git clone --depth=1 https://github.com/xiaoqingfengATGH/luci-theme-infinityfreedom package/luci-theme-infinityfreedom
git_sparse_clone main https://github.com/haiibo/packages luci-theme-atmaterial luci-theme-opentomcat luci-theme-netgear

./scripts/feeds update -a
./scripts/feeds install -a
