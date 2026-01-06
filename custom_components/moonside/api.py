"""API client that mirrors the Homebridge Moonside plugin."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote

from aiohttp import ClientResponse, ClientSession

from .const import FIREBASE_API_KEY, LOGGER, STREAM_RECONNECT_DELAY

DeviceState = dict[str, Any]
DeviceUpdateCallback = Callable[[str, DeviceState | None], Awaitable[None] | None]
StreamErrorCallback = Callable[[Exception], Awaitable[None] | None]
BeforeConnectCallback = Callable[[], Awaitable[None] | None]

FIREBASE_IDENTITY_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
FIREBASE_TOKEN_REFRESH_URL = "https://securetoken.googleapis.com/v1/token"
REALTIME_DATABASE_URL = "https://moonside-501a1.firebaseio.com"
FIRESTORE_RUNQUERY_URL = (
    "https://firestore.googleapis.com/v1/projects/moonside-501a1/databases/(default)/documents:runQuery"
)


class MoonsideApiError(Exception):
    """Base error for the Moonside API."""


class MoonsideAuthenticationError(MoonsideApiError):
    """Raised when credentials are rejected."""


class MoonsideCommunicationError(MoonsideApiError):
    """Raised for generic API failures."""


@dataclass(slots=True)
class ThemeDefinition:
    """Represents an effect that can be triggered via THEME commands."""

    id: str
    name: str
    control_data: str


class MoonsideApiClient:
    """Low level HTTP client used by the integration."""

    def __init__(
        self,
        session: ClientSession,
        email: str,
        password: str,
        api_key: str = FIREBASE_API_KEY,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._api_key = api_key
        self._id_token: str | None = None
        self._refresh_token: str | None = None
        self._local_id: str | None = None
        self._token_expiry = 0.0
        self._stream_task: asyncio.Task[None] | None = None

    async def async_close(self) -> None:
        if self._stream_task:
            self._stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stream_task
            self._stream_task = None

    async def async_fetch_devices(self) -> dict[str, DeviceState]:
        await self._ensure_authenticated()
        url = self._build_devices_url()
        response = await self._session.get(url)
        await self._raise_for_status(response)
        payload: dict[str, DeviceState] | None = await response.json()
        if payload is None:
            return {}
        return {self._decode_key(key): value or {} for key, value in payload.items()}

    async def async_get_device_state(self, device_id: str) -> DeviceState:
        await self._ensure_authenticated()
        url = self._build_device_url(device_id)
        response = await self._session.get(url)
        await self._raise_for_status(response)
        payload: DeviceState | None = await response.json()
        return payload or {}

    async def async_send_control(self, device_id: str, command: str) -> DeviceState:
        return await self.async_patch_device(device_id, {"controlData": command})

    async def async_patch_device(self, device_id: str, payload: dict[str, Any]) -> DeviceState:
        await self._ensure_authenticated()
        url = self._build_device_url(device_id)
        response = await self._session.patch(url, json=payload)
        await self._raise_for_status(response)
        body: DeviceState | None = await response.json()
        return body or {}

    async def async_fetch_theme_library(self) -> dict[str, ThemeDefinition]:
        await self._ensure_authenticated()
        request_body = {
            "structuredQuery": {
                "from": [
                    {"collectionId": "app-lighting-effects", "allDescendants": True},
                ]
            }
        }
        response = await self._session.post(
            f"{FIRESTORE_RUNQUERY_URL}?key={self._api_key}",
            headers={"Authorization": f"Bearer {self._id_token}"},
            json=request_body,
        )
        await self._raise_for_status(response)
        payload: list[dict[str, Any]] = await response.json()
        results: dict[str, ThemeDefinition] = {}
        for entry in payload:
            document = entry.get("document") or {}
            fields: dict[str, Any] | None = document.get("fields")
            if not fields:
                continue
            name_field = fields.get("name", {}).get("stringValue")
            code_field = fields.get("themeControlCode", {}).get("stringValue")
            params_field = fields.get("themeParams")
            if not name_field or not code_field:
                continue
            params = self._parse_firestore_array(params_field)
            control_data = self._build_theme_command(code_field, params)
            theme_id = (document.get("name") or name_field).split("/")[-1]
            results[name_field.lower()] = ThemeDefinition(theme_id, name_field, control_data)
        return results

    async def async_subscribe_to_updates(
        self,
        on_update: DeviceUpdateCallback,
        on_error: StreamErrorCallback | None = None,
        on_before_connect: BeforeConnectCallback | None = None,
    ) -> Callable[[], None]:
        if self._stream_task:
            self._stream_task.cancel()
            self._stream_task = None

        loop = asyncio.get_running_loop()
        self._stream_task = loop.create_task(
            self._stream_loop(on_update, on_error, on_before_connect)
        )

        def cancel() -> None:
            if self._stream_task:
                self._stream_task.cancel()

        return cancel

    async def _stream_loop(
        self,
        on_update: DeviceUpdateCallback,
        on_error: StreamErrorCallback | None,
        on_before_connect: BeforeConnectCallback | None,
    ) -> None:
        while True:
            try:
                await self._ensure_authenticated()
                if on_before_connect:
                    await asyncio.shield(on_before_connect())
                await self._consume_event_stream(on_update)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # pylint: disable=broad-except
                if on_error:
                    maybe_await = on_error(err if isinstance(err, Exception) else Exception(str(err)))
                    if maybe_await is not None:
                        await maybe_await
                await asyncio.sleep(STREAM_RECONNECT_DELAY.total_seconds())

    async def _consume_event_stream(self, on_update: DeviceUpdateCallback) -> None:
        url = self._build_devices_url()
        headers = {"Accept": "text/event-stream"}
        async with self._session.get(url, headers=headers) as response:
            await self._raise_for_status(response)
            buffer = ""
            async for chunk in response.content.iter_chunked(1024):
                if not chunk:
                    continue
                buffer += chunk.decode("utf-8")
                buffer = buffer.replace("\r", "")
                while "\n\n" in buffer:
                    raw_event, buffer = buffer.split("\n\n", 1)
                    await self._process_event(raw_event.strip(), on_update)

    async def _process_event(self, raw_event: str, on_update: DeviceUpdateCallback) -> None:
        if not raw_event:
            return
        event_type = "message"
        data_payload = ""
        for line in raw_event.split("\n"):
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_payload += line[5:].strip()
        if event_type not in {"put", "patch"} or not data_payload:
            return
        payload = json.loads(data_payload)
        await self._handle_stream_payload(payload, on_update)

    async def _handle_stream_payload(self, payload: dict[str, Any], on_update: DeviceUpdateCallback) -> None:
        path = payload.get("path", "/")
        data = payload.get("data")
        if path == "/" and isinstance(data, dict):
            for encoded_id, state in data.items():
                device_id = self._decode_key(encoded_id)
                await self._maybe_await(on_update(device_id, state))
            return
        trimmed = path[1:] if path.startswith("/") else path
        if not trimmed:
            return
        segments = trimmed.split("/")
        encoded_device_id = segments.pop(0)
        device_id = self._decode_key(encoded_device_id)
        if data is None:
            await self._maybe_await(on_update(device_id, None))
            return
        inflated = self._inflate_nested_data(segments, data)
        await self._maybe_await(on_update(device_id, inflated))

    def _inflate_nested_data(self, path: list[str], value: Any) -> Any:
        for key in reversed(path):
            value = {key: value}
        return value

    async def _ensure_authenticated(self) -> None:
        now = time.monotonic()
        if self._id_token and now < self._token_expiry:
            return
        if self._refresh_token:
            try:
                await self._refresh()
                return
            except MoonsideApiError:
                LOGGER.warning("Moonside token refresh failed, logging in again")
        await self._login()

    async def _login(self) -> None:
        payload = {
            "email": self._email,
            "password": self._password,
            "returnSecureToken": True,
        }
        response = await self._session.post(
            f"{FIREBASE_IDENTITY_URL}?key={self._api_key}",
            json=payload,
        )
        await self._raise_for_status(response, auth_request=True)
        data = await response.json()
        self._id_token = data["idToken"]
        self._refresh_token = data["refreshToken"]
        self._local_id = data["localId"]
        expires_in = int(data.get("expiresIn", "3600"))
        self._token_expiry = time.monotonic() + max(expires_in - 120, 60)

    async def _refresh(self) -> None:
        if not self._refresh_token:
            await self._login()
            return
        payload = {"grant_type": "refresh_token", "refresh_token": self._refresh_token}
        response = await self._session.post(
            f"{FIREBASE_TOKEN_REFRESH_URL}?key={self._api_key}",
            json=payload,
        )
        await self._raise_for_status(response, auth_request=True)
        data = await response.json()
        self._id_token = data["id_token"]
        self._refresh_token = data["refresh_token"]
        self._local_id = data["user_id"]
        expires_in = int(data.get("expires_in", "3600"))
        self._token_expiry = time.monotonic() + max(expires_in - 120, 60)

    def _build_device_url(self, device_id: str) -> str:
        if not self._local_id or not self._id_token:
            raise MoonsideAuthenticationError("Client is not authenticated")
        encoded_device = self._encode_key(device_id)
        return (
            f"{REALTIME_DATABASE_URL}/userDevices/{self._local_id}/{encoded_device}.json?auth={self._id_token}"
        )

    def _build_devices_url(self) -> str:
        if not self._local_id or not self._id_token:
            raise MoonsideAuthenticationError("Client is not authenticated")
        return f"{REALTIME_DATABASE_URL}/userDevices/{self._local_id}.json?auth={self._id_token}"

    @staticmethod
    def _encode_key(value: str) -> str:
        return quote(value, safe="")

    @staticmethod
    def _decode_key(value: str) -> str:
        return unquote(value)

    @staticmethod
    def _build_theme_command(code: str, params: list[int]) -> str:
        suffix = "".join(f"{value}," for value in params)
        return f"THEME.{code}.{suffix}"

    @staticmethod
    def _parse_firestore_array(field: Any) -> list[int]:
        values = (field or {}).get("arrayValue", {}).get("values", [])
        parsed: list[int] = []
        for entry in values:
            if "integerValue" in entry:
                parsed.append(int(entry["integerValue"]))
            elif "doubleValue" in entry:
                parsed.append(int(float(entry["doubleValue"])))
        return parsed

    @staticmethod
    async def _maybe_await(result: Awaitable[None] | None) -> None:
        if result is not None:
            await result

    @staticmethod
    async def _raise_for_status(response: ClientResponse, auth_request: bool = False) -> None:
        try:
            response.raise_for_status()
        except Exception as err:  # pylint: disable=broad-except
            text = await response.text()
            LOGGER.debug("Moonside error response: %s", text)
            if response.status == 400 and auth_request:
                raise MoonsideAuthenticationError(text) from err
            raise MoonsideCommunicationError(text) from err
