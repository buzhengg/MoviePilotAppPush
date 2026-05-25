# MoviePilotAppPush

MoviePilot 插件：为 [MoviePilotApp](https://github.com/yourname/MoviePilotApp) 提供 **APNs 远程推送**。

## 仓库结构

```
MoviePilotAppPush/
├── package.json              # v1 插件清单（含 "v2": true）
├── package.v2.json           # MoviePilot v2 插件清单
├── icons/
│   └── moviepilotapppush.png # 市场图标
├── plugins/
│   └── moviepilotapppush/    # v1 路径（兼容）
└── plugins.v2/
    └── moviepilotapppush/    # v2 安装路径（MoviePilot v2 使用）
        ├── __init__.py
        └── apns_client.py
```

修改插件代码后，请同步两份目录：

```bash
./scripts/sync-plugin.sh
```

## 发布到 GitHub

1. 在 GitHub 新建**公开**仓库（默认分支 `main`），例如 `MoviePilotAppPush`
2. 将本目录推送到仓库根目录：

```bash
cd docs/MoviePilotAppPush   # 或你的 clone 路径
git init
git add .
git commit -m "feat: MoviePilot App 推送插件 v1.0.0"
git branch -M main
git remote add origin git@github.com:<你的用户名>/MoviePilotAppPush.git
git push -u origin main
```

## 在 MoviePilot 在线安装

### 1. 添加插件市场源

MoviePilot Web → **插件** → **插件市场设置**，在 `PLUGIN_MARKET` 中追加（逗号分隔）：

```
https://github.com/<你的用户名>/MoviePilotAppPush
```

保存后刷新插件市场。

> 也可在部署环境设置环境变量 `PLUGIN_MARKET`，修改后重启 MoviePilot。

### 2. 安装并配置

1. **插件 → 市场**，搜索「MoviePilot App 推送」
2. 点击 **安装**（需管理员账号）
3. **已安装** 中打开插件，填写 APNs 凭证并 **启用**
   - Team ID、Key ID、`.p8` 私钥内容
   - Bundle ID：`com.buzheng.MoviePilotApp`
   - Debug 包开启「沙盒环境」；TestFlight / App Store 关闭

### 3. API 安装（可选）

```bash
curl -G "https://<MoviePilot地址>/api/v1/plugin/install/MoviePilotAppPush" \
  --data-urlencode "repo_url=https://github.com/<你的用户名>/MoviePilotAppPush" \
  -H "Authorization: Bearer <管理员Token>"
```

## 本地开发安装

不发布 GitHub 时，可将本目录路径加入 MoviePilot 环境变量：

```bash
PLUGIN_LOCAL_REPO_PATHS=/path/to/MoviePilotAppPush
```

重启后在插件页从**本地**来源安装。

## App 对接 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/plugin/MoviePilotAppPush/register` | 登录后注册 device token |
| DELETE | `/api/v1/plugin/MoviePilotAppPush/unregister` | 登出时移除 token |
| GET | `/api/v1/plugin/MoviePilotAppPush/devices` | 查看当前用户已注册设备 |

注册示例：

```http
POST /api/v1/plugin/MoviePilotAppPush/register
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "device_token": "<apns_hex_token>",
  "platform": "ios"
}
```

## 依赖

无额外 Python 依赖，使用 MoviePilot 内置的 `httpx[http2]` 与 `PyJWT`。

## 许可证

与 MoviePilotApp 项目保持一致。
