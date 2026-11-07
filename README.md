# OpenWrt · x86 / 太乙云编译

x86 固件面向 J4125-4L：x86/64、UEFI、squashfs，启动分区 64 MiB、根分区 960 MiB。默认地址 `192.168.100.1`，新安装主机名 `OpenWrt`、Argon 主题。升级保留设备侧网络、SSH 端口、主机名和主题；公开固件不包含私人配置、密码、订阅、证书或登录身份。

每次手动或定时构建都会读取所选系统、feeds 和插件源的最新提交，然后只为**本次构建**固定提交号。不会长期锁定 Lucky 或其他插件版本。`sources.lock.json` 记录准确版本，便于核查和重现；`configs/x86-sources.json` 管理跟随哪些上游。

## 构建与下载

在 [x86 Actions](https://github.com/co1q84/openwrt-ci-roc/actions/workflows/x86-64-ImmortalWrt.yml) 点击 **Run workflow**。原聚合工作流继续在北京时间周六 04:00 定时构建两个目标，太乙自身的配置和脚本逻辑保持原状。

x86 产物发布到独立的 `x86-64-运行编号-尝试次数` 标签。先以草稿上传所有文件，全部成功后才公开；更新入口只选择已完成发布。每次发布包含 EFI 镜像、最终 config、manifest、源码/feed 提交清单、构建信息、对应 APK 备份包、`release.json` 和 `sha256sums`。校验失败或关键包从 defconfig/manifest 消失时停止发布。

## 功能延续与上游变化

x86 额外配置保留原有 LuCI 应用、存储/USB/igc 驱动、PPPoE、OpenClash、Lucky、Tailscale、Docker、Nikki、OpenAppFilter、SQM、打印、共享、frp、HAProxy 等能力，也保留原仓库选择的其他功能。依赖库由上游解析；不将运行配置放入编译仓库。

- 当前上游 Argon 已整合原 `luci-app-argon-config`，使用主题内置配置入口，旧设置交由上游迁移。
- Tailscale 的 OpenWrt 包关闭了不适用的自更新，统一通过固件更新；社区界面源包含旧 auto-update 设置的兼容修复。
- 原系统的 `gecoosac` 未在所选公开构建源找到对应核心包，目前不能承诺延续该独立程序。不会从设备直接复制二进制上传 GitHub。
- Lucky 等跨版本的业务配置兼容仍需要升级后验收；CI 成功与镜像检查通过不代表服务已在实机恢复。

## 路由器端更新入口

新版固件内置 `roc-update`。在 SSH 或现有 LuCI 终端使用：

```sh
roc-update check    # 检查新版、内核和包差异
roc-update prepare  # 下载、校验、分区比较、sysupgrade -T，并准备私有备份
roc-update upgrade  # 同样检查后，等待用户留存备份和明确确认才升级
```

旧固件首次使用：从 [Releases](https://github.com/co1q84/openwrt-ci-roc/releases) 中最新 `x86-64-*` 发布下载 `roc-update`，通过现有 SSH/SCP 放到路由器 `/tmp/roc-update`，运行 `sh /tmp/roc-update check`。这是可直接运行的同一个入口，无需先安装额外 LuCI 插件。`upgrade` 必须在交互终端运行，不提供跳过确认的参数。

`prepare` 和 `upgrade` 会打印本次 `/tmp/roc-update.*` 目录。先将其中 `full-backup.tar.gz` 与 `migration-backup.tar.gz` 保存到自己的电脑；**不要上传 GitHub、发到公开页面或随固件打包**。例如在电脑上使用现有管理端口：

```sh
scp -O -P 50222 root@192.168.100.1:/tmp/roc-update.实际目录/full-backup.tar.gz ./
scp -O -P 50222 root@192.168.100.1:/tmp/roc-update.实际目录/migration-backup.tar.gz ./
```

完整备份用于回到原固件时恢复配置。迁移备份保留配置和身份，并排除旧 OpenClash 可执行核心、Nikki 包代码和旧系统的软件源清单，避免覆盖新版构建产物。Docker 数据目录和任意外置存储内容不属于配置备份，须单独保留；当前空实例也不能推导未来无需备份。

更新入口核对设备、UEFI/squashfs、当前启动盘与镜像分区、SHA256 和 `sysupgrade -T`；任何失败都停止。不会猜测固定磁盘号，不执行强制刷机、分区调整或无人值守更新。真正升级前需输入备份留存确认及完整发布编号，随后由系统 sysupgrade 保留配置升级并重启。

## 恢复与验收

刷机前保留原固件下载、上述备份及本地控制台/USB 启动恢复方法。升级后确认 WAN 拨号、DNS、SSH 原端口、LuCI 主题和所有实际使用的插件业务；IPv6 的启停仍由原配置决定。版本更新后的故障通过保存的 manifest、config 和提交清单追溯，必要时使用原镜像与完整配置备份恢复。

## 文件与本地检查

- `configs/x86-64.config`、`configs/x86-packages.config`：x86 布局与功能需求。
- `configs/General.config`：两个目标原有的通用配置；x86 配置最后合并，避免套用 ARM 优化参数。
- `scripts/x86-build.py`：按次解析最新源码、准备、配置验证及发布。
- `files/x86/usr/sbin/roc-update`：设备端检查与手动确认更新。
- `configs/Taiyi.config`、太乙 workflow 与 `Roc-script.sh` 原太乙部分：继续使用原有流程。太乙仅对预先存在的 extroot 分区执行原迁移逻辑。

```sh
python3 -m unittest discover -s tests -v
shellcheck -s sh files/x86/usr/sbin/roc-update
actionlint .github/workflows/x86-64-ImmortalWrt.yml .github/workflows/Trigger-All-Workflows.yml
```

本地测试、Git push、CI 编译、镜像兼容检查与刷机后的实机业务验收是不同阶段，不应相互替代。
