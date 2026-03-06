"""Config flow for Daelim SmartHome."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import aiohttp_client

from .const import DOMAIN
from .complexes import fetch_complexes_from_daelim

_LOGGER = logging.getLogger(__name__)


def generate_uuid_from_username(username: str) -> str:
    """Generate UUID from username (MD5 hash)."""
    return hashlib.md5(username.encode()).hexdigest().lower()


async def fetch_complexes(hass: HomeAssistant) -> list[dict]:
    """Fetch complex list from Daelim SmartHome official site."""
    try:
        session = aiohttp_client.async_get_clientsession(hass)
        return await fetch_complexes_from_daelim(session)
    except Exception as err:
        _LOGGER.error("Failed to fetch complexes: %s", err)
        return []


class DaelimConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for Daelim SmartHome."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow."""
        self._complexes_data: list[dict] = []
        self._selected_region: str | None = None
        self._selected_complex: dict | None = None
        self._reauth_entry_id: str | None = None
        self._wallpad_client = None
        self._wallpad_dong: str = ""
        self._wallpad_ho: str = ""
        self._pending_username: str = ""
        self._pending_password: str = ""
        self._pending_uuid: str = ""

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle initial step - select region."""
        self._complexes_data = await fetch_complexes(self.hass)
        regions = sorted({r["region"] for r in self._complexes_data})

        if user_input is not None:
            self._selected_region = user_input["region"]
            return await self.async_step_complex()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("region"): vol.In(regions)}),
        )

    async def async_step_complex(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle complex selection."""
        if not self._selected_region:
            return self.async_abort(reason="no_region")

        complexes = []
        for r in self._complexes_data:
            if r["region"] == self._selected_region:
                complexes = r.get("complexes", [])
                break

        complex_names = sorted([c["name"] for c in complexes])

        if user_input is not None:
            for c in complexes:
                if c["name"] == user_input["complex"]:
                    self._selected_complex = c
                    break
            return await self.async_step_credentials()

        return self.async_show_form(
            step_id="complex",
            data_schema=vol.Schema({vol.Required("complex"): vol.In(complex_names)}),
        )

    async def async_step_credentials(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle credentials input."""
        if not self._selected_complex:
            return self.async_abort(reason="no_complex")

        errors: dict[str, str] = {}

        if user_input is not None:
            from .client import DaelimClient

            username = user_input["username"]
            password = user_input["password"]
            uuid = generate_uuid_from_username(username)

            client = DaelimClient(
                server_ip=self._selected_complex["serverIp"],
                username=username,
                password=password,
                uuid=uuid,
                complex_name=self._selected_complex["name"],
            )
            try:
                directory_name = self._selected_complex.get("directoryName", "")
                ok, extra = await client.try_login(directory_name)
                if ok:
                    client.disconnect()
                    return self.async_create_entry(
                        title=self._selected_complex["name"],
                        data={
                            "region": self._selected_region,
                            "complex": self._selected_complex["name"],
                            "username": username,
                            "password": password,
                            "uuid": uuid,
                            "server_ip": self._selected_complex["serverIp"],
                            "apart_id": self._selected_complex.get("apartId", ""),
                            "directory_name": self._selected_complex.get("directoryName", ""),
                        },
                    )
                if extra and extra.get("require_wallpad"):
                    self._wallpad_client = client
                    self._wallpad_dong = extra.get("dong", "")
                    self._wallpad_ho = extra.get("ho", "")
                    self._pending_username = username
                    self._pending_password = password
                    self._pending_uuid = uuid
                    return await self.async_step_wall_pad()
                client.disconnect()
            except Exception:
                client.disconnect()
                raise
            errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="credentials",
            data_schema=vol.Schema(
                {
                    vol.Required("username"): str,
                    vol.Required("password"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> FlowResult:
        """Handle reauthentication flow."""
        from .client import DaelimClient

        entry_id = self.context.get("entry_id")
        config_entry = (
            self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
        )
        if config_entry is None:
            return self.async_abort(reason="no_client")

        self._reauth_entry_id = config_entry.entry_id
        self._selected_region = config_entry.data.get("region")
        self._selected_complex = {
            "name": config_entry.data.get("complex", ""),
            "serverIp": config_entry.data.get("server_ip", ""),
            "apartId": config_entry.data.get("apart_id", ""),
            "directoryName": config_entry.data.get("directory_name", ""),
        }

        username = config_entry.data["username"]
        password = config_entry.data["password"]
        uuid = config_entry.data.get("uuid") or generate_uuid_from_username(username)

        client = DaelimClient(
            server_ip=self._selected_complex["serverIp"],
            username=username,
            password=password,
            uuid=uuid,
            complex_name=self._selected_complex["name"],
        )

        try:
            ok, extra = await client.try_login(self._selected_complex.get("directoryName", ""))
            if ok:
                client.disconnect()
                return await self.async_update_reload_and_abort(
                    config_entry,
                    data_updates={"uuid": uuid},
                )

            if extra and extra.get("require_wallpad"):
                self._wallpad_client = client
                self._wallpad_dong = extra.get("dong", "")
                self._wallpad_ho = extra.get("ho", "")
                self._pending_username = username
                self._pending_password = password
                self._pending_uuid = uuid
                return await self.async_step_wall_pad()

            client.disconnect()
            return self.async_abort(reason="invalid_auth")
        except Exception:
            client.disconnect()
            raise

    async def async_step_wall_pad(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle wall pad certification number input."""
        if not self._wallpad_client:
            return self.async_abort(reason="no_client")

        errors: dict[str, str] = {}

        if user_input is not None:
            wallpad_number = user_input.get("wallpad_number", "").strip()
            if not wallpad_number:
                errors["base"] = "wallpad_required"
            else:
                ok, err = await self._wallpad_client.submit_wallpad(
                    self._wallpad_dong,
                    self._wallpad_ho,
                    wallpad_number,
                )
                if ok:
                    self._wallpad_client.disconnect()
                    self._wallpad_client = None
                    if self._reauth_entry_id:
                        reauth_entry = self.hass.config_entries.async_get_entry(
                            self._reauth_entry_id
                        )
                        self._reauth_entry_id = None
                        if reauth_entry is None:
                            return self.async_abort(reason="no_client")
                        return await self.async_update_reload_and_abort(
                            reauth_entry,
                            data_updates={"uuid": self._pending_uuid},
                        )
                    return self.async_create_entry(
                        title=self._selected_complex["name"],
                        data={
                            "region": self._selected_region,
                            "complex": self._selected_complex["name"],
                            "username": self._pending_username,
                            "password": self._pending_password,
                            "uuid": self._pending_uuid,
                            "server_ip": self._selected_complex["serverIp"],
                            "apart_id": self._selected_complex.get("apartId", ""),
                            "directory_name": self._selected_complex.get("directoryName", ""),
                        },
                    )
                if err == "invalid_wallpad":
                    errors["base"] = "invalid_wallpad"
                else:
                    errors["base"] = "invalid_auth"
                    self._wallpad_client.disconnect()
                    self._wallpad_client = None
                    return self.async_abort(reason="wallpad_failed")

        return self.async_show_form(
            step_id="wall_pad",
            data_schema=vol.Schema(
                {vol.Required("wallpad_number"): str}
            ),
            description_placeholders={
                "dong": self._wallpad_dong or "-",
                "ho": self._wallpad_ho or "-",
            },
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> DaelimOptionsFlow:
        """Get options flow."""
        return DaelimOptionsFlow(config_entry)


class DaelimOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Daelim SmartHome."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options or {}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "group_by_type",
                        default=options.get("group_by_type", True),
                    ): bool,
                    vol.Optional(
                        "door_duration",
                        default=options.get("door_duration", 5),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
                    vol.Optional(
                        "vehicle_duration",
                        default=options.get("vehicle_duration", 5),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
                    vol.Optional(
                        "camera_duration",
                        default=options.get("camera_duration", 180),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=600)),
                }
            ),
        )
