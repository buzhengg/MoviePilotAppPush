"""
MoviePilot App 远程推送插件。

在线安装：将本仓库加入 MoviePilot PLUGIN_MARKET 后，在插件市场安装 MoviePilotAppPush。
本地安装：PLUGIN_LOCAL_REPO_PATHS 指向仓库根目录。

App API：
  POST   /api/v1/plugin/MoviePilotAppPush/register
  DELETE /api/v1/plugin/MoviePilotAppPush/unregister
  GET    /api/v1/plugin/MoviePilotAppPush/devices
  GET/POST /api/v1/plugin/MoviePilotAppPush/test_push  （插件详情页测试推送）
"""
from __future__ import annotations

import copy
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Body, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas
from app.core.config import settings
from app.db import get_async_db
from app.db.models import User
from app.db.user_oper import get_current_active_user_async
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import Notification

from .apns_client import APNsClient, APNsSendResult

PLUGIN_ID = "MoviePilotAppPush"
DEVICE_REGISTRY_KEY = "device_registry"
LAST_TEST_PUSH_KEY = "last_test_push"
DEFAULT_BUNDLE_ID = "com.buzheng.MoviePilotApp"
DEFAULT_TEST_TITLE = "MoviePilot 测试推送"
DEFAULT_TEST_BODY = "这是一条来自 MoviePilotAppPush 插件的测试通知"


class DeviceRegisterRequest(BaseModel):
    device_token: str = Field(..., min_length=1, description="APNs device token（hex）")
    platform: str = Field(default="ios", description="ios / macos")
    bundle_id: Optional[str] = Field(default=None, description="App Bundle ID，默认取插件配置")


class DeviceUnregisterRequest(BaseModel):
    device_token: str = Field(..., min_length=1)


class TestPushRequest(BaseModel):
    username: Optional[str] = Field(default=None, description="仅推送给该用户；留空则按 device_token 或全部设备")
    device_token: Optional[str] = Field(default=None, description="仅推送给指定 token")
    title: str = Field(default=DEFAULT_TEST_TITLE)
    message: str = Field(default=DEFAULT_TEST_BODY, description="通知正文")
    link: Optional[str] = Field(default=None, description="通知附带链接（可选）")


class MoviePilotAppPush(_PluginBase):
    plugin_name = "MoviePilot App 推送"
    plugin_desc = "为 MoviePilot iOS / macOS App 提供 APNs 远程推送"
    plugin_version = "1.1.0"
    plugin_author = "MoviePilotApp"
    # 与 package.v2.json 的 icon 一致；独立仓库须用 raw.githubusercontent.com 完整 URL
    plugin_icon = "https://raw.githubusercontent.com/buzhengg/MoviePilotAppPush/main/icons/moviepilotapppush.png"
    plugin_order = 120

    def __init__(self):
        super().__init__()
        self._config: dict = {}
        self._enabled = False
        self._apns: Optional[APNsClient] = None
        self._lock = threading.Lock()

    def init_plugin(self, config: dict = None):
        self._config = config or {}
        self._enabled = bool(self._config.get("enabled"))
        self._rebuild_apns_client()

    def get_state(self) -> bool:
        return self._enabled

    def stop_service(self):
        with self._lock:
            if self._apns:
                self._apns.close()
            self._apns = None

    def _rebuild_apns_client(self) -> None:
        with self._lock:
            if self._apns:
                self._apns.close()
            self._apns = APNsClient(
                team_id=str(self._config.get("team_id") or ""),
                key_id=str(self._config.get("key_id") or ""),
                auth_key=str(self._config.get("auth_key") or ""),
                bundle_id=str(self._config.get("bundle_id") or DEFAULT_BUNDLE_ID),
                use_sandbox=bool(self._config.get("use_sandbox", True)),
            )

    def _apns_ready(self) -> bool:
        client = self._apns
        return bool(self._enabled and client and client.is_configured)

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {
                                        "model": "enabled",
                                        "label": "启用 App 推送",
                                        "color": "primary",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {
                                        "model": "use_sandbox",
                                        "label": "使用 APNs 沙盒环境",
                                        "color": "warning",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {
                                        "model": "push_broadcast",
                                        "label": "未指定用户时推送给所有已注册设备",
                                        "color": "info",
                                    },
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "team_id",
                                        "label": "Apple Team ID",
                                        "placeholder": "10 位 Team ID",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "key_id",
                                        "label": "APNs Key ID",
                                        "placeholder": "AuthKey 的 Key ID",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "bundle_id",
                                        "label": "Bundle ID",
                                        "placeholder": DEFAULT_BUNDLE_ID,
                                    },
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [{
                                    "component": "VTextarea",
                                    "props": {
                                        "model": "auth_key",
                                        "label": "APNs Auth Key (.p8 文件内容)",
                                        "placeholder": "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----",
                                        "rows": 6,
                                        "auto-grow": True,
                                    },
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": (
                                "App 登录后调用 POST /api/v1/plugin/MoviePilotAppPush/register 上报 device token。"
                                "Debug 包请开启「沙盒环境」；TestFlight / App Store 请关闭。"
                            ),
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "use_sandbox": True,
            "push_broadcast": True,
            "team_id": "",
            "key_id": "",
            "auth_key": "",
            "bundle_id": DEFAULT_BUNDLE_ID,
        }

    def get_page(self) -> Optional[List[dict]]:
        return self._build_detail_page()

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/register",
                "endpoint": self.register_device,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "注册 App 设备 token",
                "description": "MoviePilot App 登录后上报 APNs device token，绑定当前用户。",
            },
            {
                "path": "/unregister",
                "endpoint": self.unregister_device,
                "methods": ["DELETE"],
                "auth": "bear",
                "summary": "注销 App 设备 token",
                "description": "App 登出或关闭推送时移除 device token。",
            },
            {
                "path": "/devices",
                "endpoint": self.list_my_devices,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "列出当前用户已注册设备",
            },
            {
                "path": "/test_push",
                "endpoint": self.test_push,
                "methods": ["GET", "POST"],
                "summary": "发送测试推送（插件详情页）",
                "description": "管理员在插件详情页测试 APNs；GET 供页面按钮调用，POST 可提交 JSON。",
            },
        ]

    async def register_device(
            self,
            body: DeviceRegisterRequest,
            current_user: User = Depends(get_current_active_user_async),
            db: AsyncSession = Depends(get_async_db),
    ) -> schemas.Response:
        _ = db
        username = current_user.name
        token = self._normalize_token(body.device_token)
        if not token:
            return schemas.Response(success=False, message="device token 无效")

        registry = self._load_registry()
        devices = registry.get(username, [])
        now = datetime.now().isoformat(timespec="seconds")
        bundle_id = (body.bundle_id or self._config.get("bundle_id") or DEFAULT_BUNDLE_ID).strip()
        platform = (body.platform or "ios").strip().lower()

        updated = False
        for item in devices:
            if item.get("device_token") == token:
                item.update({
                    "platform": platform,
                    "bundle_id": bundle_id,
                    "updated_at": now,
                })
                updated = True
                break

        if not updated:
            devices.append({
                "device_token": token,
                "platform": platform,
                "bundle_id": bundle_id,
                "updated_at": now,
            })

        registry[username] = devices
        self._save_registry(registry)
        logger.info("App 推送：用户 %s 注册 device token（%s）", username, token[:12] + "...")
        return schemas.Response(
            success=True,
            message="device token 已注册",
            data={"username": username, "device_count": len(devices)},
        )

    async def unregister_device(
            self,
            body: DeviceUnregisterRequest,
            current_user: User = Depends(get_current_active_user_async),
            db: AsyncSession = Depends(get_async_db),
    ) -> schemas.Response:
        _ = db
        username = current_user.name
        token = self._normalize_token(body.device_token)
        registry = self._load_registry()
        devices = registry.get(username, [])
        registry[username] = [d for d in devices if d.get("device_token") != token]
        self._save_registry(registry)
        return schemas.Response(success=True, message="device token 已移除")

    async def list_my_devices(
            self,
            current_user: User = Depends(get_current_active_user_async),
            db: AsyncSession = Depends(get_async_db),
    ) -> schemas.Response:
        _ = db
        username = current_user.name
        devices = self._load_registry().get(username, [])
        masked = [
            {
                "platform": d.get("platform"),
                "bundle_id": d.get("bundle_id"),
                "updated_at": d.get("updated_at"),
                "device_token": (d.get("device_token") or "")[:12] + "...",
            }
            for d in devices
        ]
        return schemas.Response(success=True, data={"devices": masked})

    async def test_push(
            self,
            apikey: str = "",
            username: Optional[str] = None,
            device_token: Optional[str] = None,
            title: str = DEFAULT_TEST_TITLE,
            message: str = DEFAULT_TEST_BODY,
            link: Optional[str] = None,
            payload: Optional[TestPushRequest] = Body(None),
    ) -> schemas.Response:
        """插件详情页：发送测试 APNs（需 API_TOKEN）。"""
        if payload:
            username = payload.username if payload.username is not None else username
            device_token = payload.device_token if payload.device_token is not None else device_token
            title = payload.title or title
            message = payload.message or message
            link = payload.link if payload.link is not None else link

        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")

        if not self._apns_ready():
            return schemas.Response(
                success=False,
                message="插件未启用或 APNs 未配置完整，请先在插件配置中填写 Team ID / Key ID / .p8 / Bundle ID",
            )

        targets = self._resolve_test_push_targets(username, device_token)
        if not targets:
            hint = "暂无已注册设备"
            if username:
                hint = f"用户 {username} 暂无已注册设备"
            elif device_token:
                hint = "未找到匹配的 device token"
            return schemas.Response(success=False, message=hint)

        push_title = (title or DEFAULT_TEST_TITLE).strip() or DEFAULT_TEST_TITLE
        push_body = (message or DEFAULT_TEST_BODY).strip() or DEFAULT_TEST_BODY

        sent = 0
        failed: List[dict] = []
        for uname, token in targets:
            result = self._send_to_device(
                token=token,
                title=push_title,
                body=push_body,
                link=link,
                mtype="test",
            )
            if result.success:
                sent += 1
            else:
                failed.append({
                    "username": uname,
                    "device_token": token,
                    "reason": result.reason or f"HTTP {result.status_code}",
                })

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        summary = f"已向 {sent}/{len(targets)} 个设备发送测试推送"
        self.save_data(LAST_TEST_PUSH_KEY, {
            "time": now,
            "title": push_title,
            "message": push_body,
            "username": username,
            "device_token": device_token,
            "sent": sent,
            "total": len(targets),
            "failed": failed,
        })

        if failed and sent:
            return schemas.Response(
                success=True,
                message=f"{summary}，{len(failed)} 个失败",
                data={"sent": sent, "failed": failed},
            )
        if failed:
            return schemas.Response(
                success=False,
                message=f"推送失败：{failed[0].get('reason', '未知错误')}",
                data={"sent": 0, "failed": failed},
            )
        return schemas.Response(success=True, message=summary, data={"sent": sent})

    def get_module(self) -> Dict[str, Any]:
        return {"post_message": self.send_push}

    def send_push(self, message: Notification, **kwargs) -> None:
        if not self._apns_ready():
            return None

        title = (message.title or "").strip() or "MoviePilot"
        body = (message.text or "").strip()
        if not body and not message.title:
            return None

        usernames = self._resolve_target_usernames(message)
        if not usernames:
            return None

        registry = self._load_registry()
        sent = 0
        invalid_tokens: List[Tuple[str, str]] = []

        for username in usernames:
            for device in registry.get(username, []):
                token = device.get("device_token")
                if not token:
                    continue
                result = self._send_to_device(
                    token=token,
                    title=title,
                    body=body,
                    link=message.link,
                    mtype=message.mtype.value if message.mtype else None,
                )
                if result.success:
                    sent += 1
                elif APNsClient.should_remove_token(result):
                    invalid_tokens.append((username, token))

        if invalid_tokens:
            self._remove_invalid_tokens(invalid_tokens)

        if sent:
            logger.info("App 推送：已向 %d 个设备发送「%s」", sent, title)
        return None

    @staticmethod
    def _normalize_token(raw: str) -> str:
        return (raw or "").strip().replace(" ", "").replace("<", "").replace(">", "")

    def _load_registry(self) -> Dict[str, List[dict]]:
        data = self.get_data(DEVICE_REGISTRY_KEY)
        if isinstance(data, dict):
            return copy.deepcopy(data)
        return {}

    def _save_registry(self, registry: Dict[str, List[dict]]) -> None:
        self.save_data(DEVICE_REGISTRY_KEY, registry)

    def _resolve_target_usernames(self, message: Notification) -> List[str]:
        if message.username:
            return [str(message.username)]

        if self._config.get("push_broadcast", True):
            registry = self._load_registry()
            if registry:
                return list(registry.keys())

        return []

    def _send_to_device(
            self,
            *,
            token: str,
            title: str,
            body: str,
            link: Optional[str],
            mtype: Optional[str],
    ) -> APNsSendResult:
        with self._lock:
            client = self._apns
            if not client:
                return APNsSendResult(
                    device_token=token, success=False, status_code=0, reason="client unavailable"
                )

        custom = {}
        if mtype:
            custom["mtype"] = mtype

        return client.send(
            token,
            title=title,
            body=body,
            link=link,
            custom=custom or None,
        )

    def _remove_invalid_tokens(self, invalid: List[Tuple[str, str]]) -> None:
        registry = self._load_registry()
        changed = False
        for username, bad_token in invalid:
            devices = registry.get(username, [])
            filtered = [d for d in devices if d.get("device_token") != bad_token]
            if len(filtered) != len(devices):
                registry[username] = filtered
                changed = True
                logger.info("App 推送：移除失效 token 用户=%s token=%s...", username, bad_token[:12])

        if changed:
            self._save_registry(registry)

    def _resolve_test_push_targets(
            self,
            username: Optional[str],
            device_token: Optional[str],
    ) -> List[Tuple[str, str]]:
        registry = self._load_registry()
        token_filter = self._normalize_token(device_token or "") if device_token else ""

        if token_filter:
            for uname, devices in registry.items():
                for device in devices:
                    token = device.get("device_token") or ""
                    if token == token_filter:
                        return [(uname, token)]
            return []

        if username:
            devices = registry.get(username, [])
            return [
                (username, d.get("device_token"))
                for d in devices
                if d.get("device_token")
            ]

        targets: List[Tuple[str, str]] = []
        for uname, devices in registry.items():
            for device in devices:
                token = device.get("device_token")
                if token:
                    targets.append((uname, token))
        return targets

    def _page_test_push_event(
            self,
            *,
            username: str = "",
            device_token: str = "",
            title: str = "",
            message: str = "",
    ) -> dict:
        params: Dict[str, Any] = {"apikey": settings.API_TOKEN}
        if username:
            params["username"] = username
        if device_token:
            params["device_token"] = device_token
        if title:
            params["title"] = title
        if message:
            params["message"] = message
        return {
            "api": f"plugin/{PLUGIN_ID}/test_push",
            "method": "get",
            "params": params,
        }

    def _build_detail_page(self) -> List[dict]:
        registry = self._load_registry()
        apns_status = self._detail_apns_status_text()
        last_test = self.get_data(LAST_TEST_PUSH_KEY) or {}

        page: List[dict] = [
            {
                "component": "VAlert",
                "props": {
                    "type": "success" if self._apns_ready() else "warning",
                    "variant": "tonal",
                    "text": apns_status,
                },
            },
        ]

        if last_test:
            failed_count = len(last_test.get("failed") or [])
            last_msg = (
                f"最近测试：{last_test.get('time', '—')}，"
                f"成功 {last_test.get('sent', 0)}/{last_test.get('total', 0)}"
            )
            if failed_count:
                last_msg += f"，失败 {failed_count} 个"
            page.append({
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "text": last_msg,
                },
            })

        if not registry:
            page.append({
                "component": "div",
                "text": "暂无已注册设备。请使用 MoviePilot App 登录并允许通知权限。",
                "props": {"class": "text-center text-medium-emphasis py-6"},
            })
            return page

        total_users = len(registry)
        total_devices = sum(len(devices) for devices in registry.values())
        page.append({
            "component": "VRow",
            "content": [
                {
                    "component": "VCol",
                    "props": {"cols": 12, "md": 4},
                    "content": [{
                        "component": "VCard",
                        "props": {"variant": "tonal"},
                        "content": [
                            {"component": "VCardTitle", "text": str(total_users)},
                            {"component": "VCardSubtitle", "text": "已注册用户"},
                        ],
                    }],
                },
                {
                    "component": "VCol",
                    "props": {"cols": 12, "md": 4},
                    "content": [{
                        "component": "VCard",
                        "props": {"variant": "tonal"},
                        "content": [
                            {"component": "VCardTitle", "text": str(total_devices)},
                            {"component": "VCardSubtitle", "text": "已注册设备"},
                        ],
                    }],
                },
                {
                    "component": "VCol",
                    "props": {"cols": 12, "md": 4},
                    "content": [{
                        "component": "VBtn",
                        "props": {
                            "color": "primary",
                            "block": True,
                            "prependIcon": "mdi-bell-ring",
                        },
                        "text": "向全部设备发送测试推送",
                        "events": {
                            "click": self._page_test_push_event(),
                        },
                    }],
                },
            ],
        })

        table_headers = [
            {"text": "用户名", "class": "text-start"},
            {"text": "平台", "class": "text-start"},
            {"text": "Bundle ID", "class": "text-start"},
            {"text": "Device Token", "class": "text-start"},
            {"text": "更新时间", "class": "text-start"},
            {"text": "操作", "class": "text-start"},
        ]
        header_row = {
            "component": "thead",
            "content": [
                {
                    "component": "th",
                    "props": {"class": h["class"]},
                    "text": h["text"],
                }
                for h in table_headers
            ],
        }

        table_rows: List[dict] = []
        for username in sorted(registry.keys()):
            for device in registry.get(username, []):
                token = device.get("device_token") or ""
                if not token:
                    continue
                table_rows.append({
                    "component": "tr",
                    "props": {"class": "text-sm"},
                    "content": [
                        {"component": "td", "text": username},
                        {"component": "td", "text": device.get("platform") or "—"},
                        {"component": "td", "text": device.get("bundle_id") or "—"},
                        {
                            "component": "td",
                            "props": {"class": "font-mono text-caption", "style": "word-break: break-all; max-width: 360px;"},
                            "text": token,
                        },
                        {"component": "td", "text": device.get("updated_at") or "—"},
                        {
                            "component": "td",
                            "content": [{
                                "component": "VBtn",
                                "props": {
                                    "color": "primary",
                                    "size": "small",
                                    "variant": "tonal",
                                },
                                "text": "测试推送",
                                "events": {
                                    "click": self._page_test_push_event(
                                        username=username,
                                        device_token=token,
                                    ),
                                },
                            }],
                        },
                    ],
                })

        page.append({
            "component": "VCol",
            "props": {"cols": 12},
            "content": [{
                "component": "VCard",
                "content": [
                    {"component": "VCardTitle", "text": "已注册设备"},
                    {
                        "component": "VCardText",
                        "content": [{
                            "component": "VTable",
                            "props": {"hover": True, "density": "comfortable"},
                            "content": [
                                header_row,
                                {"component": "tbody", "content": table_rows},
                            ],
                        }],
                    },
                ],
            }],
        })

        page.append({
            "component": "VAlert",
            "props": {
                "type": "info",
                "variant": "tonal",
                "text": (
                    "点击「测试推送」将向对应设备发送默认测试通知。"
                    "请确认 APNs 沙盒/生产环境与 App 构建类型一致。"
                ),
            },
        })

        return [{"component": "VRow", "content": [{"component": "VCol", "props": {"cols": 12}, "content": page}]}]

    def _detail_apns_status_text(self) -> str:
        if not self._enabled:
            return "插件未启用：请在插件配置中打开「启用 App 推送」"
        client = self._apns
        if not client or not client.is_configured:
            return "APNs 未配置完整：请填写 Team ID、Key ID、.p8 内容与 Bundle ID"
        env = "沙盒" if self._config.get("use_sandbox", True) else "生产"
        bundle = self._config.get("bundle_id") or DEFAULT_BUNDLE_ID
        return f"APNs 已就绪（{env}），Bundle ID：{bundle}"
