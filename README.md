# OpenWrt · x86 / 太乙云编译

x86 固件面向 J4125-4L：x86/64、UEFI，同时产出 squashfs 与 ext4 两种镜像（分区布局相同），启动分区 64 MiB、根分区 960 MiB。默认地址 `192.168.100.1`，新安装主机名 `OpenWrt`、Argon 主题。升级保留设备侧网络、SSH 端口、主机名和主题；公开固件不包含私人配置、密码、订阅、证书或登录身份。

每次手动或定时构建都会读取所选系统、feeds 和插件源的最新提交，然后只为**本次构建**固定提交号。不会长期锁定 Lucky 或其他插件版本。`sources.lock.json` 记录准确版本，便于核查和重现；`configs/x86-sources.json` 管理跟随哪些上游。

## 构建与下载

在 [x86 Actions](https://github.com/co1q84/openwrt-ci-roc/actions/workflows/x86-64-ImmortalWrt.yml) 点击 **Run workflow**。原聚合工作流继续在北京时间周六 04:00 定时构建两个目标，太乙自身的配置和脚本逻辑保持原状。

x86 产物发布到独立的 `x86-64-运行编号-尝试次数` 标签，每次发布成功后只保留最新 4 个（其他发布线不动）。定时编译错峰：x86 每周六 04:00，太乙每周日 04:00；手动运行“Trigger-All”时两者依次执行。先以草稿上传所有文件，全部成功后才公开；更新入口只选择已完成发布。每次发布包含 squashfs 与 ext4 两个 EFI 镜像（`firmware-update` 只升级 squashfs 版，ext4 版手动写入）、最终 config、manifest、源码/feed 提交清单、构建信息、对应 APK 备份包、`release.json` 和 `sha256sums`。校验失败或关键包从 defconfig/manifest 消失时停止发布。

## 功能延续与上游变化

x86 以本机实际使用为准：保留 Tailscale、OpenClash（内核来自 mihomo-meta）、Lucky、Docker、SQM、看门狗/定时重启、网络唤醒、存储/USB/igc 驱动、PPPoE 及基础 LuCI。已移除本机未使用或仅有示例配置的 frp、HAProxy、Samba/wsdd2/avahi、Nikki、OpenAppFilter、sing-box/xray、Shadowsocks/SSR 命令行、banIP、DDNS（由 Lucky 负责）、ACME、3cat、socat、wifischedule、arpbind、aria2/AriaNg（NAS 已提供）、WireGuard（由 Tailscale 组网）、USB 打印、hd-idle（SSD 系统盘不应休眠）、gecoosac、Aurora 主题、HomeProxy、iStore、dufs、FileBrowser 及旧 PassWall 遗留组件；不再生成 ISO/虚拟机镜像，不含 kexec。保留 UPnP 与 KMS（vlmcsd），新增 Vantage 主题及配套面板（默认主题仍为 Argon）、wechatpush 异常通知与 vnstat2 流量统计。共享的 `General.config` 不变，x86 仅在自身配置中关闭，太乙不受影响。依赖库由上游解析；不将运行配置放入编译仓库。

- 新内核的 x86/64 显示继续使用 DRM/i915，旧 fbdev 包已限制为 legacy/geode；Netfilter 日志采用合并后的 `kmod-nf-log`，iptables 功能由现有 ipt/nft 兼容模块承接。输入与 USB 打印显式启用其支持包。
- 当前上游 Argon 已整合原 `luci-app-argon-config`，使用主题内置配置入口，旧设置交由上游迁移。
- Tailscale 的 OpenWrt 包关闭了不适用的自更新，统一通过固件更新；社区界面源包含旧 auto-update 设置的兼容修复。
- 出厂/重置默认值按本机硬件设置：管理地址 `192.168.100.1`；网口 eth0 为 WAN，eth1–eth3 桥接为 LAN（上游通用默认为 eth0 作 LAN、eth1 作 WAN）。只影响无配置的首次启动，恢复的配置优先。
- Lucky 等跨版本的业务配置兼容仍需要升级后验收；CI 成功与镜像检查通过不代表服务已在实机恢复。

## 路由器端更新入口

新版固件内置 `firmware-update`。在 SSH 或现有 LuCI 终端使用：

```sh
firmware-update check    # 检查新版、内核和包差异
firmware-update prepare  # 下载、校验、分区比较、sysupgrade -T，并准备私有备份
firmware-update upgrade  # 同样检查后，等待用户留存备份和明确确认才升级
firmware-update verify   # 重新核对升级后配置是否全部生效
firmware-update rollback # 回到上一个版本及离开它时的配置（需 SSD 数据分区）
firmware-update migrate /dev/sda  # 从当前系统把新固件装到另一块 SSD（一次性）
```

升级前额外检查启动分区可写、空间足够且读回一致（系统 sysupgrade 复制配置时不检查结果）。备份内附关键设置的哈希与必需文件清单（不含明文）；新固件首次启动由 `config-check` 逐项核对，结果写入 `/etc/firmware-update/last-check`，不一致按 err 级别记录（进入 SSD 异常日志），`check` 时会显示上次结果。

有 SSD 数据分区时，每次升级在 `/mnt/data/firmware/` 保留新镜像（含 SHA256）和离开当前版本那一刻的配置，只保留当前与上一个版本；`rollback` 校验镜像、分区和确认 `ROLLBACK 版本号` 后执行，并把被离开的版本记为下一次可回到的版本。

旧固件首次使用：从 [Releases](https://github.com/co1q84/openwrt-ci-roc/releases) 中最新 `x86-64-*` 发布下载 `firmware-update`，通过现有 SSH/SCP 放到路由器 `/tmp/firmware-update`，运行 `sh /tmp/firmware-update check`。这是可直接运行的同一个入口，无需先安装额外 LuCI 插件。`upgrade` 必须在交互终端运行，不提供跳过确认的参数。

`prepare` 和 `upgrade` 会打印本次 `/tmp/firmware-update.*` 目录。先将其中 `full-backup.tar.gz` 与 `migration-backup.tar.gz` 保存到自己的电脑；**不要上传 GitHub、发到公开页面或随固件打包**。例如在电脑上使用现有管理端口：

```sh
scp -O -P 50222 root@192.168.100.1:/tmp/firmware-update.实际目录/full-backup.tar.gz ./
scp -O -P 50222 root@192.168.100.1:/tmp/firmware-update.实际目录/migration-backup.tar.gz ./
```

完整备份用于回到原固件时恢复配置。迁移备份保留配置和身份，并排除旧 OpenClash 可执行核心、已移除的 Nikki 数据和旧系统的软件源清单，避免覆盖新版构建产物。Docker 数据目录和任意外置存储内容不属于配置备份，须单独保留；当前空实例也不能推导未来无需备份。

下载经 GitHub API 获取发布文件，优先走本机 OpenClash 混合端口（读取其认证配置，密码只经标准输入交给 curl），失败再直连；完整性以 SHA256 为准。更新入口核对设备、UEFI/squashfs、当前启动盘与镜像分区、SHA256 和 `sysupgrade -T`；任何失败都停止。不会猜测固定磁盘号，不执行强制刷机、分区调整或无人值守更新。真正升级前需输入备份留存确认及完整发布编号，随后由系统 sysupgrade 保留配置升级并重启。

## 迁移到 SSD 与数据分区

`migrate` 在当前（U 盘）系统上运行，不改动当前系统盘：

1. 拒绝当前启动盘、可移动设备、有挂载或交换分区的盘及容量不足的盘；拒绝与当前启动盘系统分区 ID 相同的镜像（两盘同时在位会启动错乱）。
2. 下载并校验发布镜像，做配置备份，要求输入 `ERASE /dev/目标盘`。
3. 整盘写入镜像并读回比对 SHA256；把 GPT 备份头移到盘尾，从 4 GiB 处创建 ext4 数据分区（`data`），核对系统分区未变。
4. 在迁移配置中写入最终状态，经 uci 逐项读回确认后放入新启动分区的 `sysupgrade.tgz`，首次启动自动恢复：
   - 数据分区挂载到 `/mnt/data`，Docker 数据目录 `/mnt/data/docker/`；
   - IPv6 仅路由器 WAN 获取（`wan.ipv6=1`、wan6 跟随 PPPoE），LAN 不分配、不通告、不解析 AAAA，代理流量保持 IPv4；
   - watchcat 检测 223.5.5.5 与 119.29.29.29：10 分钟不通执行 `wan-redial` 重拨，原重启规则周期不变。

完成后在 BIOS 中把 SSD 设为第一启动项，U 盘保留作回退。之后在 SSD 上 `upgrade` 只重写启动与系统分区，数据分区保留；系统分区大小不可再改。

vnstat 流量历史首次启动时默认存到 `/mnt/data/vnstat`、统计 eth0（已设置的不覆盖）。数据分区挂载后，`error-log` 服务只把 warn 及以上级别和 watchcat 事件写到 `/mnt/data/log/error.log`（10 MiB 轮换一份），排除 Tailscale 的常规输出；未挂载时不写系统分区。

## 恢复与验收

刷机前保留原固件下载、上述备份及本地控制台/USB 启动恢复方法。升级后确认 WAN 拨号、DNS、SSH 原端口、LuCI 主题和所有实际使用的插件业务；IPv6 的启停仍由原配置决定。版本更新后的故障通过保存的 manifest、config 和提交清单追溯，必要时使用原镜像与完整配置备份恢复。

## 文件与本地检查

- `configs/x86-64.config`、`configs/x86-packages.config`：x86 布局与功能需求。
- `configs/General.config`：两个目标原有的通用配置；x86 配置最后合并，避免套用 ARM 优化参数。
- `scripts/x86-build.py`：按次解析最新源码、准备、配置验证及发布。
- `files/x86/usr/sbin/firmware-update`：设备端检查、手动确认更新及 SSD 迁移。
- `files/x86/usr/libexec/error-log`、`files/x86/etc/init.d/error-log`：异常日志落盘。
- `configs/Taiyi.config`、太乙 workflow 与 `Roc-script.sh` 原太乙部分：继续使用原有流程。太乙仅对预先存在的 extroot 分区执行原迁移逻辑。

```sh
python3 -m unittest discover -s tests -v
shellcheck -s sh files/x86/usr/sbin/firmware-update files/x86/usr/libexec/error-log
actionlint .github/workflows/x86-64-ImmortalWrt.yml .github/workflows/Trigger-All-Workflows.yml
```

本地测试、Git push、CI 编译、镜像兼容检查与刷机后的实机业务验收是不同阶段，不应相互替代。
