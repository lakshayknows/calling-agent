"""Plivo adapter implementing the TelephonyProvider port.

Talks to Plivo's REST API over HTTP with basic auth. Business logic depends on
`TelephonyProvider`, so swapping Plivo for another carrier later means writing a
new adapter here — nothing else changes.
"""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.core.exceptions import ProviderError
from app.providers.base import (
    CallHandle,
    CallStatus,
    OutboundCallRequest,
    TelephonyProvider,
)


class PlivoProvider(TelephonyProvider):
    def __init__(self, settings: Settings) -> None:
        self._auth_id = settings.plivo_auth_id
        self._auth_token = settings.plivo_auth_token
        self._base = settings.plivo_base_url.rstrip("/")

    @property
    def _account_url(self) -> str:
        return f"{self._base}/v1/Account/{self._auth_id}"

    @property
    def _auth(self) -> tuple[str, str]:
        return (self._auth_id, self._auth_token)

    async def place_call(self, request: OutboundCallRequest) -> CallHandle:
        payload: dict[str, object] = {
            "from": request.from_number,
            "to": request.to_number,
            "answer_url": request.answer_url,
            "answer_method": "GET",
        }
        if request.hangup_url:
            payload["hangup_url"] = request.hangup_url
            payload["hangup_method"] = "POST"

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{self._account_url}/Call/", json=payload, auth=self._auth
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Plivo request failed: {exc}") from exc

        if resp.status_code not in (200, 201, 202):
            raise ProviderError(f"Plivo error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        return CallHandle(
            provider_call_id=data.get("request_uuid", ""),
            status=CallStatus.QUEUED,
            raw=data,
        )

    async def hangup(self, provider_call_id: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                await client.delete(
                    f"{self._account_url}/Call/{provider_call_id}/", auth=self._auth
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Plivo hangup failed: {exc}") from exc

    async def transfer(self, provider_call_id: str, to_number: str) -> None:
        # Redirects the live call to a transfer XML that dials `to_number`.
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{self._account_url}/Call/{provider_call_id}/",
                    json={"legs": "aleg", "aleg_url": to_number},
                    auth=self._auth,
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Plivo transfer failed: {exc}") from exc
        if resp.status_code not in (200, 202):
            raise ProviderError(f"Plivo transfer error {resp.status_code}: {resp.text[:200]}")

    async def list_numbers(self) -> list[dict[str, object]]:
        """Not part of the port — a convenience for discovering caller IDs."""
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(f"{self._account_url}/Number/", auth=self._auth)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Plivo list numbers failed: {exc}") from exc
        if resp.status_code != 200:
            raise ProviderError(f"Plivo error {resp.status_code}: {resp.text[:200]}")
        return resp.json().get("objects", [])
