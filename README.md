<div align="center">
<h1>OpenWrt - x86 / 太乙 云编译</h1>

## 项目说明

- 默认管理地址：**`192.168.100.1`**
- 默认用户：**`root`**
- 默认密码：**`none`**
- 当前仓库只保留两个产品：**`x86-64`** 与 **`太乙(jdcloud_re-cs-07)`**

## 功能范围

- 保留路由器基础管理能力与常用存储能力
- 第三方应用仅保留：`HomeProxy`、`OpenClash`、`Lucky`、`Watchcat`、`banIP`、`Dufs`、`FileBrowser`、`Vlmcsd`、`iStore`
- 同时保留 `Docker` 与 `NAS` 相关入口
- 其余第三方服务与无关目标机型已移除

## 存储与应用更新策略

- **x86-64**：切换为可写 `ext4` 根文件系统，在线更新应用时不会再受 `squashfs + overlay` 空间回收问题影响
- **太乙**：继续使用稳定的 `squashfs sysupgrade` 路径；固件不再自动改分区，只会在你预先准备好并标记为 `extroot` 的 `ext4` 分区存在时，自动迁移 `overlay`

## 使用方式

- `configs/x86-64.config`：x86-64 目标配置
- `configs/Taiyi.config`：太乙目标配置
- `configs/General.config`：通用包与基础能力配置
- `scripts/Roc-script.sh`：主题、第三方源与太乙 extroot 初始化逻辑

## 工作流

- `.github/workflows/x86-64-ImmortalWrt.yml`
- `.github/workflows/Taiyi-ImmortalWrt.yml`
- `.github/workflows/Trigger-All-Workflows.yml`

## 说明

- 构建前请根据需要进一步调整 `configs/*.config`
- 若需修改默认 IP、主机名、附加 feed 或首次启动脚本，请修改 `scripts/Roc-script.sh`
- 固件默认主题为 `Argon`，并预置 `Asia/Shanghai` 时区
- 太乙若要扩展应用安装空间，请先在 eMMC 上准备一个 `ext4` 分区，并设置文件系统标签为 `extroot`
- 固件编译完成后，可在仓库 Releases 对应标签下载镜像
