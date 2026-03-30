#!/bin/bash
# HR 市场情报查看器 — 一键安装脚本
# 用法: curl -fsSL https://raw.githubusercontent.com/jujuwin22/wechat-intel/main/install.sh | bash
#
# 自动检测已安装的 AI 编程工具，将情报查看规则安装到对应的全局规则目录。
# 支持: Claude Code / CodeBuddy / Cursor / Windsurf

set -e

REPO="jujuwin22/wechat-intel"
RAW_BASE="https://raw.githubusercontent.com/${REPO}/main"
RULE_URL="${RAW_BASE}/AGENTS.md"

echo "================================================"
echo "  HR 市场情报查看器 — 安装程序"
echo "================================================"
echo ""

# 下载规则内容
echo "正在从 GitHub 下载规则文件..."
RULE_CONTENT=$(curl -fsSL "$RULE_URL" 2>/dev/null)
if [ -z "$RULE_CONTENT" ]; then
    echo "错误: 无法下载规则文件，请检查网络连接"
    exit 1
fi
echo "下载成功"
echo ""

INSTALLED=0

# ─── Claude Code ───
CLAUDE_SKILL_DIR="$HOME/.claude/skills/wechat-intel-viewer"
if [ -d "$HOME/.claude" ]; then
    echo "[Claude Code] 检测到 Claude Code"
    echo "  正在下载完整 skill..."

    # 创建 skill 目录
    mkdir -p "$CLAUDE_SKILL_DIR/scripts"
    mkdir -p "$CLAUDE_SKILL_DIR/templates"

    # 下载 SKILL.md
    curl -fsSL "${RAW_BASE}/skills/wechat-intel-viewer/SKILL.md" > "$CLAUDE_SKILL_DIR/SKILL.md" 2>/dev/null

    # 下载脚本
    curl -fsSL "${RAW_BASE}/skills/wechat-intel-viewer/scripts/generate_html.py" > "$CLAUDE_SKILL_DIR/scripts/generate_html.py" 2>/dev/null
    chmod +x "$CLAUDE_SKILL_DIR/scripts/generate_html.py"

    # 下载模板
    curl -fsSL "${RAW_BASE}/skills/wechat-intel-viewer/templates/digest-report.md" > "$CLAUDE_SKILL_DIR/templates/digest-report.md" 2>/dev/null
    curl -fsSL "${RAW_BASE}/skills/wechat-intel-viewer/templates/trend-report.md" > "$CLAUDE_SKILL_DIR/templates/trend-report.md" 2>/dev/null

    if [ -f "$CLAUDE_SKILL_DIR/SKILL.md" ]; then
        echo "  ✅ 已安装到: $CLAUDE_SKILL_DIR"
        echo "     版本: $(grep 'version:' $CLAUDE_SKILL_DIR/SKILL.md | head -1 | cut -d':' -f2 | tr -d ' ')"
    else
        echo "  ❌ 安装失败，请检查网络连接"
    fi
    INSTALLED=$((INSTALLED + 1))
    echo ""
fi

# ─── CodeBuddy ───
CODEBUDDY_DIR="$HOME/.codebuddy"
if command -v codebuddy &>/dev/null || [ -d "$CODEBUDDY_DIR" ]; then
    echo "[CodeBuddy] 检测到 CodeBuddy"
    mkdir -p "$CODEBUDDY_DIR"
    # CodeBuddy 使用 CODEBUDDY.md 作为全局规则
    echo "$RULE_CONTENT" > "$CODEBUDDY_DIR/CODEBUDDY.md"
    echo "  已安装到: $CODEBUDDY_DIR/CODEBUDDY.md"
    INSTALLED=$((INSTALLED + 1))
    echo ""
fi

# ─── Cursor ───
CURSOR_RULES_DIR="$HOME/.cursor/rules"
if [ -d "$HOME/.cursor" ] || [ -d "$HOME/Library/Application Support/Cursor" ]; then
    echo "[Cursor] 检测到 Cursor"
    mkdir -p "$CURSOR_RULES_DIR"
    # Cursor 使用 .mdc 格式 (Markdown + YAML frontmatter)
    cat > "$CURSOR_RULES_DIR/wechat-intel-viewer.mdc" << 'CURSOR_EOF'
---
description: "HR 市场情报查看器 — 查询已采集的微信公众号HR情报数据，支持按公司/维度/时间筛选，生成趋势报告"
alwaysApply: false
---

CURSOR_EOF
    echo "$RULE_CONTENT" >> "$CURSOR_RULES_DIR/wechat-intel-viewer.mdc"
    echo "  已安装到: $CURSOR_RULES_DIR/wechat-intel-viewer.mdc"
    INSTALLED=$((INSTALLED + 1))
    echo ""
fi

# ─── Windsurf ───
WINDSURF_RULES_DIR="$HOME/.codeium/windsurf/memories"
if [ -d "$HOME/.codeium" ] || command -v windsurf &>/dev/null; then
    echo "[Windsurf] 检测到 Windsurf"
    mkdir -p "$WINDSURF_RULES_DIR"
    # Windsurf 使用 global_rules.md
    echo "$RULE_CONTENT" > "$WINDSURF_RULES_DIR/wechat-intel-viewer.md"
    echo "  已安装到: $WINDSURF_RULES_DIR/wechat-intel-viewer.md"
    INSTALLED=$((INSTALLED + 1))
    echo ""
fi

# ─── 未检测到任何工具 ───
if [ $INSTALLED -eq 0 ]; then
    echo "未检测到已安装的 AI 编程工具 (Claude Code / CodeBuddy / Cursor / Windsurf)"
    echo ""
    echo "手动安装方式:"
    echo "  1. 将以下 URL 的内容保存到你的 AI 工具的规则目录:"
    echo "     $RULE_URL"
    echo ""
    echo "  2. 或者在对话中直接告诉 AI:"
    echo "     \"先读一下 $RULE_URL ，然后帮我查HR情报\""
    exit 0
fi

echo "================================================"
echo "  安装完成! 已安装到 $INSTALLED 个工具"
echo "================================================"
echo ""
echo "使用方法: 在 AI 工具中直接说"
echo "  - \"查一下字节跳动最近的HR动态\""
echo "  - \"3月薪酬激励有哪些事件\""
echo "  - \"生成3月趋势报告\""
echo ""
echo "数据来源: https://github.com/${REPO}"
echo "数据由 shihang 每月更新"
