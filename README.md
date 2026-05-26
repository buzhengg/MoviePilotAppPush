# MoviePilotAppPush

MoviePilot 插件：为 MoviePilot iOS / macOS App 提供 **APNs 远程推送**。

仓库：<https://github.com/buzhengg/MoviePilotAppPush>

## 仓库结构（对齐 MoviePilot 插件规范）

```
MoviePilotAppPush/
├── package.json              # v1 清单；条目内 "v2": true 表示兼容 MP v2
├── package.v2.json           # MoviePilot v2 优先读取此清单
├── icons/
│   └── moviepilotapppush.png
├── plugins/
│   └── moviepilotapppush/
└── plugins.v2/
    └── moviepilotapppush/    # v2 在线安装实际下载此目录
        ├── __init__.py
        └── apns_client.py
```

### 命名约定

| 项目 | 值 |
|------|-----|
| `package*.json` 的 key | `MoviePilotAppPush` |
| 目录名 | `moviepilotapppush` |
| 安装后路径 | `MoviePilot/app/plugins/moviepilotapppush/` |

## 发布 / 更新

```bash
cd docs/MoviePilotAppPush
git add .
git commit -m "chore: update plugin"
git push origin main
```

默认分支须为 **`main`**，仓库须为 **public**。

## 在线安装

### 1. 添加市场源

MoviePilot Web → **插件** → **插件市场设置**，追加：

```
https://github.com/buzhengg/MoviePilotAppPush
```

### 2. 安装

**插件 → 市场** → 搜索「MoviePilot App 推送」→ **安装** → 配置 APNs → **启用**。

### 3. API 安装（可选）

```bash
curl -G "https://<MoviePilot地址>/api/v1/plugin/install/MoviePilotAppPush" \
  --data-urlencode "repo_url=https://github.com/buzhengg/MoviePilotAppPush" \
  -H "Authorization: Bearer <管理员Token>"
```

## 本地开发安装

```bash
PLUGIN_LOCAL_REPO_PATHS=/path/to/MoviePilotAppPush
```

## 改代码后同步

```bash
./scripts/sync-plugin.sh
```

## 插件详情页（v1.1.0+）

安装并启用后，在 **插件 → MoviePilot App 推送 → 详情** 可：

- 查看 **已注册用户数 / 设备数** 与 APNs 配置状态
- 表格展示 **用户名、平台、Bundle ID、完整 device token、更新时间**
- **单设备测试推送** 或 **向全部设备发送测试推送**
- 页面顶部显示最近一次测试结果

## App API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/plugin/MoviePilotAppPush/register` | App 登录后注册 token |
| DELETE | `/api/v1/plugin/MoviePilotAppPush/unregister` | App 登出注销 token |
| GET | `/api/v1/plugin/MoviePilotAppPush/devices` | 当前用户已注册设备（脱敏） |
| GET/POST | `/api/v1/plugin/MoviePilotAppPush/test_push` | 测试推送（管理员 Bearer） |
