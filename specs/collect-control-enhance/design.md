# 技术设计: 采集控制增强（水位线管理 + 公众号选择采集）

## 1. 架构概述

```
前端 CollectView.vue
  ├─ 水位线管理区域 (新增清除按钮)
  ├─ 公众号勾选列表 (新增)
  └─ 开始采集 (传入 accounts 参数)
       │
       ▼
后端 app.py
  ├─ DELETE /api/collect/watermark/<name>  (新增)
  ├─ DELETE /api/collect/watermark         (新增)
  ├─ GET    /api/collect/accounts          (新增)
  └─ POST   /api/collect/run  { accounts: [...] }  (扩展)
       │
       ▼
collector.py --accounts "涛哥杂谈,大厂日爆"  (扩展CLI)
```

## 2. API 设计

### 2.1 获取公众号列表（新增）
```
GET /api/collect/accounts
Response: {
  "accounts": [
    {"name": "涛哥杂谈", "id": "jerryhetalk", "feed_id": "MP_WXS_...", "dimensions": [...]}
  ]
}
```
数据来源：`wechat_channels.yaml` → `config.load_wechat_channels()`

### 2.2 清除单个水位线（新增）
```
DELETE /api/collect/watermark/<account_name>
Response: {"status": "ok", "message": "已清除 涛哥杂谈 的水位线"}
```

### 2.3 清除全部水位线（新增）
```
DELETE /api/collect/watermark
Response: {"status": "ok", "message": "已清除全部水位线"}
```

### 2.4 启动采集（扩展）
```
POST /api/collect/run
Body: {
  "start_date": "2026-03-01",
  "end_date": "2026-03-27",
  "accounts": ["涛哥杂谈", "大厂日爆"]  // 新增，为空则全部采集
}
```
后端将 accounts 列表拼接为 `--accounts "涛哥杂谈,大厂日爆"` 传给 collector CLI。

## 3. 关键组件

### 3.1 后端改动 (`server/app.py`)
- 新增 `GET /api/collect/accounts`：读取 wechat_channels.yaml 返回公众号列表
- 新增 `DELETE /api/collect/watermark/<name>`：删除 watermark.json 中指定 key
- 新增 `DELETE /api/collect/watermark`：清空 watermark.json
- 修改 `POST /api/collect/run`：接收 accounts 参数，构建 `--accounts` CLI 参数

### 3.2 采集器改动 (`server/collector/config.py`)
- 新增 `--accounts` 参数（逗号分隔的公众号名称列表）
- 兼容现有 `--account` 单个过滤

### 3.3 前端改动 (`frontend/src/views/CollectView.vue`)
- 水位线区域：每行增加"清除"按钮 + 底部"清除全部"按钮
- 新增公众号勾选列表区域（默认全选，带全选/全不选按钮）
- 开始采集时传入勾选的公众号列表

## 4. 测试策略
- 单元测试：验证 watermark 清除 API 的正确性
- 集成测试：勾选2个公众号 → 只采集这2个 → 验证日志中只出现这2个
- 边界测试：不勾选任何公众号 → 前端拦截提示
