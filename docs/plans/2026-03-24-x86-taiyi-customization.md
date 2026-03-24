# x86 与太乙定制实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将仓库收缩为仅支持 `x86-64` 与 `太乙(jdcloud_re-cs-07)`，保留指定第三方应用，并为 `x86` 与太乙分别提供可持续更新应用的数据写入方案。

**Architecture:** 通过精简目标配置、重写自定义脚本与收缩工作流来完成产品线裁剪。`x86` 改为可写根文件系统镜像；太乙保留 `squashfs`，并通过构建时注入的 `uci-defaults` 脚本自动挂载应用数据区，将高写入目录迁移到独立数据分区。

**Tech Stack:** OpenWrt/ImmortalWrt `.config`、GitHub Actions、Shell、LuCI 包选择、`uci-defaults`

---

### Task 1: 收缩产品目标与包选择

**Files:**
- Modify: `configs/General.config`
- Modify: `configs/x86-64.config`
- Modify: `configs/Taiyi.config`

**Step 1: 精简通用第三方包**

删除不在需求内的第三方服务，仅保留指定应用与路由基础能力需要的包。

**Step 2: 精简目标配置**

让 `x86-64` 与 `jdcloud_re-cs-07` 只启用目标产品需要的设备与补充包。

**Step 3: 校验目标配置**

Run: `rg -n "CONFIG_TARGET_DEVICE_|CONFIG_PACKAGE_luci-app-" configs/General.config configs/x86-64.config configs/Taiyi.config`
Expected: 仅出现目标产品及保留应用。

### Task 2: 重写自定义脚本

**Files:**
- Modify: `scripts/Roc-script.sh`

**Step 1: 移除无关第三方源**

删除不在需求内的软件包替换与仓库拉取逻辑。

**Step 2: 补充所需第三方源**

保留或新增 `HomeProxy`、`OpenClash`、`Lucky`、`Dufs`、`FileBrowser`、`iStore` 所需源。

**Step 3: 注入数据区初始化文件**

在脚本中创建 `files/etc/uci-defaults/99-app-data`，为太乙初始化并挂载应用数据区。

**Step 4: 校验脚本**

Run: `rg -n "passwall|frp|wechatpush|oaf|ariang|openlist2|homeproxy|openclash|dufs|filebrowser|istore" scripts/Roc-script.sh`
Expected: 仅剩保留项。

### Task 3: 收缩工作流

**Files:**
- Modify: `.github/workflows/x86-64-ImmortalWrt.yml`
- Modify: `.github/workflows/Taiyi-ImmortalWrt.yml`
- Delete: `.github/workflows/IPQ60XX-LibWrt.yml`
- Delete: `.github/workflows/IPQ807X-LibWrt.yml`
- Delete: `.github/workflows/JDCloud-ImmortalWrt.yml`
- Modify: `.github/workflows/Trigger-All-Workflows.yml`

**Step 1: 仅保留两个产品工作流**

删除与当前产品无关的工作流，并更新触发器。

**Step 2: x86 切到可写根文件系统**

调整 `x86-64` 工作流说明和配置处理，确保不再依赖 `squashfs` 假设。

**Step 3: 太乙工作流同步精简说明**

更新发布说明，反映新软件包清单与应用数据区策略。

**Step 4: 校验工作流**

Run: `ls .github/workflows`
Expected: 仅保留目标相关工作流与总触发器。

### Task 4: 端到端校验

**Files:**
- Test: `configs/*.config`
- Test: `.github/workflows/*.yml`
- Test: `scripts/Roc-script.sh`

**Step 1: 执行静态校验**

Run: `bash -n scripts/Roc-script.sh`
Expected: PASS

**Step 2: 执行仓库范围检查**

Run: `rg -n "passwall|passwall2|frpc|frps|wechatpush|aria2|ddns|oaf|openlist2" .`
Expected: 仅设计文档中允许出现，业务配置与工作流中不再出现。

**Step 3: 检查变更清单**

Run: `git diff --stat`
Expected: 变更集中在配置、工作流、脚本与文档。
