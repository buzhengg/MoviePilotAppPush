"""
MoviePilot App 远程推送插件。

在线安装：将本仓库加入 MoviePilot PLUGIN_MARKET 后，在插件市场安装 MoviePilotAppPush。
本地安装：PLUGIN_LOCAL_REPO_PATHS 指向仓库根目录。

App API：
  POST   /api/v1/plugin/MoviePilotAppPush/register
  DELETE /api/v1/plugin/MoviePilotAppPush/unregister
  GET    /api/v1/plugin/MoviePilotAppPush/devices
"""
from __future__ import annotations

import copy
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas
from app.db import get_async_db
from app.db.models import User
from app.db.user_oper import get_current_active_user_async
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import Notification

from .apns_client import APNsClient, APNsSendResult

PLUGIN_ID = "MoviePilotAppPush"
DEVICE_REGISTRY_KEY = "device_registry"
DEFAULT_BUNDLE_ID = "com.buzheng.MoviePilotApp"


class DeviceRegisterRequest(BaseModel):
    device_token: str = Field(..., min_length=1, description="APNs device token（hex）")
    platform: str = Field(default="ios", description="ios / macos")
    bundle_id: Optional[str] = Field(default=None, description="App Bundle ID，默认取插件配置")


class DeviceUnregisterRequest(BaseModel):
    device_token: str = Field(..., min_length=1)


class MoviePilotAppPush(_PluginBase):
    plugin_name = "MoviePilot App 推送"
    plugin_desc = "为 MoviePilot iOS / macOS App 提供 APNs 远程推送"
    plugin_version = "1.0.0"
    plugin_author = "MoviePilotApp"
    plugin_icon = "mdi-cellphone-message"
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
        return None

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
