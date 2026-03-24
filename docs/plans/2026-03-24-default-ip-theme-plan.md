# Default IP And Theme Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将固件默认管理地址调整为 `192.168.100.1`，默认主题调整为 `Argon`，并预置少量低风险系统默认值。

**Architecture:** 通过修改构建时脚本中的默认网络生成逻辑和第三方主题源选择完成镜像默认值调整。额外使用 `uci-defaults` 预置 LuCI 主题和时区，避免仅安装主题包但不切换默认主题的问题。

**Tech Stack:** OpenWrt `.config`、GitHub Actions 文案、Shell、`uci-defaults`

---

### Task 1: 调整默认地址与主题包

**Files:**
- Modify: `configs/General.config`
- Modify: `scripts/Roc-script.sh`

**Step 1: 切换主题包**

将通用配置从 `Aurora` 切回 `Argon`，并同步调整第三方 feed 拉取逻辑。

**Step 2: 调整默认 LAN 地址**

把镜像默认地址从 `192.168.2.1` 改为 `192.168.100.1`。

**Step 3: 添加低风险预置**

通过 `uci-defaults` 预置 `Argon` 默认主题与 `Asia/Shanghai` 时区。

**Step 4: 校验**

Run: `rg -n "192\\.168\\.100\\.1|argon|aurora|timezone|zonename|mediaurlbase" configs/General.config scripts/Roc-script.sh`
Expected: 仅出现 `192.168.100.1` 和 `argon` 相关配置。

### Task 2: 同步说明文档与工作流文案

**Files:**
- Modify: `README.md`
- Modify: `.github/workflows/x86-64-ImmortalWrt.yml`
- Modify: `.github/workflows/Taiyi-ImmortalWrt.yml`

**Step 1: 更新默认地址说明**

将对外说明中的默认地址同步更新为 `192.168.100.1`。

**Step 2: 更新主题说明**

将默认主题说明同步更新为 `Argon`。

**Step 3: 校验**

Run: `rg -n "192\\.168\\.2\\.1|Aurora|Argon|192\\.168\\.100\\.1" README.md .github/workflows`
Expected: 旧地址和旧主题说明被替换完毕。

### Task 3: 静态验证

**Files:**
- Test: `scripts/Roc-script.sh`
- Test: `README.md`
- Test: `.github/workflows/*.yml`

**Step 1: Shell 语法检查**

Run: `bash -n scripts/Roc-script.sh`
Expected: PASS

**Step 2: YAML 解析检查**

Run: `ruby -e 'require "yaml"; %w[.github/workflows/Taiyi-ImmortalWrt.yml .github/workflows/x86-64-ImmortalWrt.yml .github/workflows/Trigger-All-Workflows.yml].each { |f| YAML.load_file(f); puts "OK #{f}" }'`
Expected: 全部 `OK`
