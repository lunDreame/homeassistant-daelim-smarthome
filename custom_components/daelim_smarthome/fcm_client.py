"""FCM Push client for Daelim SmartHome."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Callable

from firebase_messaging import FcmPushClient, FcmRegisterConfig

from .const import (
    FCM_API_KEY,
    FCM_APP_ID,
    FCM_PROJECT_ID,
    FCM_SENDER_ID,
)

_LOGGER = logging.getLogger(__name__)


def _get_credentials_path(hass, entry_id: str) -> str:
    """Get path for storing FCM credentials."""
    return str(Path(hass.config.config_dir) / f".daelim_smarthome_{entry_id}_fcm.json")


def load_credentials(hass, entry_id: str) -> dict | None:
    """Load FCM credentials from disk."""
    path = _get_credentials_path(hass, entry_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as err:
        _LOGGER.warning("Failed to load FCM credentials: %s", err)
        return None


def save_credentials(hass, entry_id: str, credentials: dict) -> None:
    """Save FCM credentials to disk."""
    path = _get_credentials_path(hass, entry_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(credentials, f, indent=2)
        _LOGGER.debug("Saved FCM credentials to %s", path)
    except OSError as err:
        _LOGGER.error("Failed to save FCM credentials: %s", err)


class DaelimFcmClient:
    """FCM client wrapper for Daelim SmartHome push notifications."""

    def __init__(
        self,
        hass,
        entry_id: str,
        on_push: Callable[[int, int, dict], None],
    ) -> None:
        """Initialize FCM client."""
        self.hass = hass
        self.entry_id = entry_id
        self.on_push = on_push
        self._client: FcmPushClient | None = None
        self._credentials: dict | None = None
        self._fcm_token: str | None = None

    def _on_notification(self, data: dict, persistent_id: str, context: object) -> None:
        """Handle incoming FCM notification."""
        if not data or not isinstance(data, dict):
            return
        try:
            ptype = int(data.get("data1", data.get("type", 0)))
            sub_type = int(data.get("data2", data.get("subType", 0)))
        except (TypeError, ValueError):
            return
        _LOGGER.debug("FCM push: type=%s, subType=%s, data=%s", ptype, sub_type, data)
        self.on_push(ptype, sub_type, data)

    def _on_credentials_updated(self, credentials: dict) -> None:
        """Save credentials when updated."""
        self._credentials = credentials
        self.hass.add_job(
            self.hass.async_add_executor_job,
            save_credentials,
            self.hass,
            self.entry_id,
            credentials,
        )

    async def start(self) -> str | None:
        """Start FCM client and return FCM token for PUSH_REQUEST."""
        try:
            if self._credentials is None:
                self._credentials = await self.hass.async_add_executor_job(
                    load_credentials,
                    self.hass,
                    self.entry_id,
                )
            config = FcmRegisterConfig(
                project_id=FCM_PROJECT_ID,
                app_id=FCM_APP_ID,
                api_key=FCM_API_KEY,
                messaging_sender_id=FCM_SENDER_ID,
            )
            self._client = FcmPushClient(
                callback=self._on_notification,
                fcm_config=config,
                credentials=self._credentials,
                credentials_updated_callback=self._on_credentials_updated,
            )
            self._fcm_token = await self._client.checkin_or_register()
            if not self._fcm_token:
                _LOGGER.error("FCM token not received")
                return None
            await self._client.start()
            _LOGGER.info("FCM client started, token registered")
            return self._fcm_token
        except KeyError as err:
            _LOGGER.error("FCM credentials structure error: %s", err)
            return None
        except Exception as err:
            _LOGGER.error("FCM client start failed: %s", err)
            return None

    async def stop(self) -> None:
        """Stop FCM client."""
        if self._client:
            try:
                await self._client.stop()
            except Exception as err:
                _LOGGER.debug("FCM stop error: %s", err)
            self._client = None
        self._fcm_token = None
