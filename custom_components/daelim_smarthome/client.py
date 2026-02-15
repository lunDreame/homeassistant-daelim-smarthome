"""Daelim SmartHome MMF protocol client."""

from __future__ import annotations

import asyncio
import json
import struct
import logging
from typing import Any

from .const import (
    MMF_SERVER_PORT,
    Types,
    DeviceSubTypes,
    LoginSubTypes,
    SettingSubTypes,
    ElevatorCallSubTypes,
    InfoSubTypes,
    Errors,
)

_LOGGER = logging.getLogger(__name__)

HEADER_SIZE = 24


def create_packet(body: dict, pin: str, ptype: int, sub_type: int) -> bytes:
    """Create MMF protocol packet."""
    header = pin.encode("utf-8").ljust(8)[:8]
    header += struct.pack("<i", ptype)
    header += struct.pack("<i", sub_type)
    header += struct.pack("<h", 1)
    header += struct.pack("<h", 3)
    header += struct.pack("<b", Errors.SUCCESS)
    header += b"\x00\x00\x00"

    body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
    packet = header + body_bytes
    return struct.pack("<i", len(packet)) + packet


def parse_chunk(data: bytes) -> tuple[bytes, int] | None:
    """Parse chunk - returns (packet_data, total_size) or None if incomplete."""
    if len(data) < 4:
        return None
    length = struct.unpack("<i", data[:4])[0]
    if length <= 0 or length > 1024 * 1024:
        return None
    if len(data) < 4 + length:
        return None
    return data[4 : 4 + length], 4 + length


def parse_packet_body(packet_data: bytes) -> tuple[dict, int, int, int]:
    """Parse packet body - returns (body, ptype, sub_type, error)."""
    ptype = struct.unpack("<i", packet_data[8:12])[0]
    sub_type = struct.unpack("<i", packet_data[12:16])[0]
    error = struct.unpack("<b", packet_data[20:21])[0]
    body_str = packet_data[HEADER_SIZE:].decode("utf-8", errors="ignore")
    try:
        body = json.loads(body_str) if body_str else {}
    except json.JSONDecodeError:
        body = {}
    return body, ptype, sub_type, error


class DaelimClient:
    """Async Daelim SmartHome MMF client."""

    def __init__(
        self,
        server_ip: str,
        username: str,
        password: str,
        uuid: str,
        complex_name: str,
    ) -> None:
        """Initialize client."""
        self.server_ip = server_ip
        self.username = username
        self.password = password
        self.uuid = uuid
        self.complex_name = complex_name
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pin = "00000000"
        self._login_pin = ""
        self._dong = ""
        self._ho = ""
        self._connected = False
        self._read_buffer = b""
        self._read_task: asyncio.Task | None = None
        self._response_futures: dict[tuple[int, int], asyncio.Future] = {}
        self._lock = asyncio.Lock()

    def _get_pin(self) -> str:
        """Get authorization PIN."""
        return self._login_pin if len(self._login_pin) == 8 else self._pin

    async def connect(self) -> bool:
        """Connect to MMF server."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.server_ip, MMF_SERVER_PORT),
                timeout=10,
            )
            self._connected = True
            self._read_buffer = b""
            self._read_task = asyncio.create_task(self._read_loop())
            _LOGGER.info("Connected to MMF server %s", self.server_ip)
            return True
        except (asyncio.TimeoutError, OSError) as err:
            _LOGGER.error("Connection failed: %s", err)
            return False

    def disconnect(self) -> None:
        """Disconnect from server."""
        self._connected = False
        if self._read_task:
            self._read_task.cancel()
            self._read_task = None
        for future in self._response_futures.values():
            if not future.done():
                future.set_result(None)
        self._response_futures.clear()
        if self._writer:
            try:
                self._writer.close()
            except OSError:
                pass
            self._writer = None
            self._reader = None

    async def _read_loop(self) -> None:
        """Background task to read and dispatch packets."""
        while self._connected and self._reader:
            try:
                data = await self._reader.read(4096)
                if not data:
                    break
                self._read_buffer += data
                while self._read_buffer:
                    result = parse_chunk(self._read_buffer)
                    if result is None:
                        break
                    packet_data, consumed = result
                    self._read_buffer = self._read_buffer[consumed:]
                    body, ptype, sub_type, error = parse_packet_body(packet_data)
                    key = (ptype, sub_type)
                    if key in self._response_futures:
                        future = self._response_futures.pop(key)
                        if not future.done():
                            future.set_result((body, error))
            except asyncio.CancelledError:
                break
            except (ConnectionResetError, BrokenPipeError, OSError):
                break
        self._connected = False

    async def _send_request(
        self,
        body: dict,
        ptype: int,
        sub_type: int,
    ) -> None:
        """Send request (fire-and-forget)."""
        if not self._writer:
            return
        data = create_packet(body, self._get_pin(), ptype, sub_type)
        self._writer.write(data)
        await self._writer.drain()

    async def send_unreliable_request(
        self,
        body: dict,
        ptype: int,
        sub_type: int,
    ) -> None:
        """Send request without waiting for response (fire-and-forget)."""
        if not self._writer:
            return
        data = create_packet(body, self._get_pin(), ptype, sub_type)
        self._writer.write(data)
        await self._writer.drain()

    async def _request_response(
        self,
        body: dict,
        ptype: int,
        from_sub: int,
        to_sub: int,
        timeout: float = 10.0,
    ) -> tuple[dict | None, int]:
        """Send request and wait for matching response. Returns (body, error_code)."""
        async with self._lock:
            key = (ptype, to_sub)
            future: asyncio.Future[tuple[dict, int]] = asyncio.Future()
            self._response_futures[key] = future
            await self._send_request(body, ptype, from_sub)
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self._response_futures.pop(key, None)
            return (None, -1)
        finally:
            self._response_futures.pop(key, None)

    async def _do_certification_step(
        self,
        directory_name: str | None,
    ) -> tuple[bool | str, dict | None]:
        """
        Do certification PIN step.
        Returns (True, None) on success.
        Returns (False, None) on failure.
        Returns ("require_wallpad", {"dong": d, "ho": h}) when wall pad auth needed.
        """
        cert_body = {"id": self.username, "pw": self.password, "UUID": self.uuid}
        cert_resp, cert_err = await self._request_response(
            cert_body,
            Types.LOGIN,
            LoginSubTypes.CERTIFICATION_PIN_REQUEST,
            LoginSubTypes.CERTIFICATION_PIN_RESPONSE,
        )

        if cert_err == Errors.SUCCESS and cert_resp:
            self._pin = cert_resp.get("certpin", "00000000")
            self._dong = cert_resp.get("dong", "")
            self._ho = cert_resp.get("ho", "")
            return (True, None)

        if cert_err in (Errors.UNCERTIFIED_DEVICE, Errors.REGISTRATION_NOT_COMPLETED):
            await self.send_unreliable_request(
                {"id": self.username, "pw": self.password},
                Types.LOGIN,
                LoginSubTypes.DELETE_CERTIFICATION_REQUEST,
            )
            if cert_err == Errors.UNCERTIFIED_DEVICE:
                await self.send_unreliable_request(
                    {"id": self.username},
                    Types.LOGIN,
                    LoginSubTypes.APPROVAL_DELETE_REQUEST,
                )

            dong = (cert_resp or {}).get("dong", "") or (directory_name or "")
            ho = (cert_resp or {}).get("ho", "")

            await self.send_unreliable_request(
                {
                    "dong": dong,
                    "ho": ho,
                    "id": self.username,
                    "auth": 2,
                },
                Types.LOGIN,
                LoginSubTypes.APPROVAL_REQUEST,
            )
            return ("require_wallpad", {"require_wallpad": True, "dong": dong, "ho": ho})

        _LOGGER.error("Certification PIN failed, error=%s", cert_err)
        return (False, None)

    async def submit_wallpad(
        self,
        dong: str,
        ho: str,
        wallpad_number: str,
    ) -> tuple[bool, str | None]:
        """
        Submit wall pad number and retry certification.
        Returns (True, None) on success.
        Returns (False, "invalid_wallpad") on wrong number.
        Returns (False, None) on other error.
        """
        body = {
            "dong": dong,
            "ho": ho,
            "id": self.username,
            "num": str(wallpad_number),
        }
        resp, err = await self._request_response(
            body,
            Types.LOGIN,
            LoginSubTypes.WALL_PAD_REQUEST,
            LoginSubTypes.WALL_PAD_RESPONSE,
            timeout=30.0,
        )
        if err == Errors.INVALID_CERTIFICATION_NUMBER:
            return (False, "invalid_wallpad")
        if err != Errors.SUCCESS or not resp:
            return (False, None)
        cert_ok, _ = await self._do_certification_step(None)
        if cert_ok is not True:
            return (False, None)
        return (await self._finish_login(), None)

    async def try_login(
        self,
        directory_name: str | None = None,
    ) -> tuple[bool, dict | None]:
        """
        Attempt login. Returns (True, None) on success.
        Returns (False, {"require_wallpad": True, "dong": d, "ho": h}) when wall pad needed.
        Returns (False, None) on other failure.
        When require_wallpad, client stays connected for submit_wallpad().
        """
        if not await self.connect():
            return (False, None)

        cert_res, cert_extra = await self._do_certification_step(directory_name)
        if cert_res is False:
            return (False, None)
        if cert_res == "require_wallpad" and cert_extra:
            return (False, cert_extra)

        # Certification OK, continue login
        success = await self._finish_login()
        return (success, None)

    async def _finish_login(self) -> bool:
        """Complete login after certification (Login PIN, Menu, push prefs)."""
        login_body = {
            "id": self.username,
            "pw": self.password,
            "certpin": self._pin,
        }
        login_resp, login_err = await self._request_response(
            login_body,
            Types.LOGIN,
            LoginSubTypes.LOGIN_PIN_REQUEST,
            LoginSubTypes.LOGIN_PIN_RESPONSE,
        )
        if not login_resp or login_err != Errors.SUCCESS:
            _LOGGER.error("Login PIN failed")
            return False

        self._login_pin = login_resp.get("loginpin", "")

        # Step 3: Menu request
        menu_body = {}
        menu_resp, menu_err = await self._request_response(
            menu_body,
            Types.LOGIN,
            LoginSubTypes.MENU_REQUEST,
            LoginSubTypes.MENU_RESPONSE,
        )
        if not menu_resp or menu_err != Errors.SUCCESS:
            _LOGGER.error("Menu request failed")
            return False

        self._menu_response = menu_resp

        # Push preferences (door, car, visitor for camera)
        try:
            push_resp, _ = await self._request_response(
                {"type": "query", "item": [{"name": "all"}]},
                Types.SETTING,
                SettingSubTypes.PUSH_QUERY_REQUEST,
                SettingSubTypes.PUSH_QUERY_RESPONSE,
            )
            if push_resp:
                for name in ("door", "car", "visitor"):
                    items = push_resp.get("item") or []
                    enabled = any(
                        it.get("name") == name and it.get("arg1") == "on"
                        for it in items
                    )
                    if not enabled:
                        await self._request_response(
                            {
                                "type": "setting",
                                "item": [{"name": name, "arg1": "on"}],
                            },
                            Types.SETTING,
                            SettingSubTypes.PUSH_SETTING_REQUEST,
                            SettingSubTypes.PUSH_SETTING_RESPONSE,
                        )  # ignore result
        except Exception as err:
            _LOGGER.warning("Push preferences setup failed: %s", err)

        _LOGGER.info("Login successful")
        return True

    async def login(self, directory_name: str | None = None) -> bool:
        """Perform login flow (convenience wrapper)."""
        ok, _ = await self.try_login(directory_name)
        return ok

    async def register_push_token(self, fcm_token: str) -> None:
        """Register FCM token with MMF server for push delivery."""
        await self.send_unreliable_request(
            {
                "dong": self._dong,
                "ho": self._ho,
                "pushID": fcm_token,
                "phoneType": "android",
            },
            Types.LOGIN,
            LoginSubTypes.PUSH_REQUEST,
        )
        _LOGGER.info("Registered FCM token with MMF server")

    @property
    def menu_response(self) -> dict:
        """Get last menu response (controlinfo, etc)."""
        return getattr(self, "_menu_response", {})

    async def device_query(self, device_type: str, uid: str = "all") -> dict | None:
        """Query device state."""
        body = {"type": "query", "item": [{"device": device_type, "uid": uid}]}
        resp, err = await self._request_response(
            body,
            Types.DEVICE,
            DeviceSubTypes.QUERY_REQUEST,
            DeviceSubTypes.QUERY_RESPONSE,
        )
        return resp if err == Errors.SUCCESS else None

    async def device_invoke(
        self,
        device_type: str,
        uid: str,
        arg1: str,
        arg2: str | None = None,
        arg3: str | None = None,
    ) -> dict | None:
        """Invoke device command."""
        item = {"device": device_type, "uid": uid, "arg1": arg1}
        if arg2 is not None:
            item["arg2"] = arg2
        if arg3 is not None:
            item["arg3"] = arg3
        body = {"type": "invoke", "item": [item]}
        resp, err = await self._request_response(
            body,
            Types.DEVICE,
            DeviceSubTypes.INVOKE_REQUEST,
            DeviceSubTypes.INVOKE_RESPONSE,
        )
        return resp if err == Errors.SUCCESS else None

    async def wallsocket_invoke(
        self,
        uid: str,
        state: str,
    ) -> dict | None:
        """Invoke wall socket (outlet) command."""
        body = {
            "type": "invoke",
            "item": [{"device": "wallsocket", "uid": uid, "arg1": state}],
        }
        resp, err = await self._request_response(
            body,
            Types.DEVICE,
            DeviceSubTypes.WALL_SOCKET_INVOKE_REQUEST,
            DeviceSubTypes.WALL_SOCKET_INVOKE_RESPONSE,
        )
        return resp if err == Errors.SUCCESS else None

    async def elevator_call(self) -> dict | None:
        """Call elevator."""
        resp, err = await self._request_response(
            {},
            Types.ELEVATOR_CALL,
            ElevatorCallSubTypes.CALL_REQUEST,
            ElevatorCallSubTypes.CALL_RESPONSE,
        )
        return resp if err == Errors.SUCCESS else None

    async def visitor_list(self, page: int = 0, listcount: int = 1) -> dict | None:
        """Get visitor list."""
        body = {"page": page, "listcount": listcount}
        resp, err = await self._request_response(
            body,
            Types.INFO,
            InfoSubTypes.VISITOR_LIST_REQUEST,
            InfoSubTypes.VISITOR_LIST_RESPONSE,
        )
        return resp if err == Errors.SUCCESS else None

    async def visitor_check(self, index: int, read: str = "Y") -> dict | None:
        """Get visitor image."""
        body = {"index": index, "read": read}
        resp, err = await self._request_response(
            body,
            Types.INFO,
            InfoSubTypes.VISITOR_CHECK_REQUEST,
            InfoSubTypes.VISITOR_CHECK_RESPONSE,
        )
        return resp if err == Errors.SUCCESS else None

    async def access_list(self, page: int = 0, listcount: int = 10) -> dict | None:
        """Get access (door) log list."""
        body = {"page": page, "listcount": listcount}
        resp, err = await self._request_response(
            body,
            Types.INFO,
            InfoSubTypes.ACCESS_LIST_REQUEST,
            InfoSubTypes.ACCESS_LIST_RESPONSE,
        )
        return resp if err == Errors.SUCCESS else None

    async def car_getting_in_list(
        self, page: int = 0, listcount: int = 10
    ) -> dict | None:
        """Get car entering (parking) log list."""
        body = {"page": page, "listcount": listcount}
        resp, err = await self._request_response(
            body,
            Types.INFO,
            InfoSubTypes.CAR_GETTING_IN_LIST_REQUEST,
            InfoSubTypes.CAR_GETTING_IN_LIST_RESPONSE,
        )
        return resp if err == Errors.SUCCESS else None
