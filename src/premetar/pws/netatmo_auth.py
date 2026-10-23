"""Optional documented OAuth refresh; token responses are never raw weather data.

No login, browser consent, credential creation or refresh-token persistence is
performed. Provide an authorized access token externally. Rotated refresh tokens
remain in memory; a separate credential manager must persist them if needed.
"""

import os

import httpx

from premetar.pws.providers import ProviderError


class NetatmoAuth:
    def __init__(self) -> None:
        self.access_token = os.getenv("NETATMO_ACCESS_TOKEN")
        self.refresh_token = os.getenv("NETATMO_REFRESH_TOKEN")
        self.disabled = False

    def headers(self) -> dict[str, str]:
        if not self.access_token or self.disabled:
            raise ProviderError("NETATMO_CREDENTIALS_UNAVAILABLE")
        return {"Authorization": "Bearer " + self.access_token}

    async def refresh(self, client: httpx.AsyncClient) -> None:
        client_id, secret = os.getenv("NETATMO_CLIENT_ID"), os.getenv("NETATMO_CLIENT_SECRET")
        if self.disabled or not self.refresh_token or not client_id or not secret:
            raise ProviderError("NETATMO_REFRESH_UNAVAILABLE")
        try:
            response = await client.post(
                "https://api.netatmo.com/oauth2/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "client_id": client_id,
                    "client_secret": secret,
                },
                follow_redirects=False,
            )
            if response.status_code in (400, 401, 403):
                self.disabled = True
                raise ProviderError("NETATMO_AUTH_DISABLED")
            response.raise_for_status()
            data = response.json()
            token, rotated = data["access_token"], data["refresh_token"]
            if (
                not isinstance(token, str)
                or not token
                or not isinstance(rotated, str)
                or not rotated
            ):
                raise ValueError
            self.access_token, self.refresh_token = token, rotated
        except (httpx.HTTPError, ValueError, KeyError):
            raise ProviderError("NETATMO_TOKEN_REFRESH_FAILED") from None
