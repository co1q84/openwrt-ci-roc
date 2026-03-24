<div align="center">
<h1>OpenWrt - x86 / 太乙 云编译</h1>

## 项目说明

- 默认管理地址：**`192.168.2.1`**
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
- **太乙**：继续使用稳定的 `squashfs sysupgrade` 路径，并在首次启动时自动将 `overlay` 迁移到 eMMC 空闲空间，避免后续应用更新被系统 overlay 空间限制

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
- 固件编译完成后，可在仓库 Releases 对应标签下载镜像
