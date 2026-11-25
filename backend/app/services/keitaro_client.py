import httpx
import logging
from typing import List, Dict, Any, Optional
from app.config import settings

logger = logging.getLogger(__name__)


class KeitaroAPIError(RuntimeError):
    """Safe, user-facing summary of an upstream Keitaro failure."""

    def __init__(self, message: str, *, http_status: int = 502, api_status: int | None = None):
        super().__init__(message)
        self.http_status = http_status
        self.api_status = api_status


class KeitaroClient:
    """HTTP client for Keitaro Admin API."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = 30.0

    def _headers(self) -> Dict[str, str]:
        """Return headers with API key."""
        return {
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    async def _request(
        self, method: str, endpoint: str, **kwargs
    ) -> Any:
        """Make an async HTTP request to Keitaro API."""
        url = f"{self.base_url}{endpoint}"
        kwargs.setdefault("headers", self._headers())
        kwargs.setdefault("timeout", self.timeout)

        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                if response.status_code == 204 or not response.content:
                    return {}
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"Keitaro API error: {method} {url} -> {e.response.status_code}"
                )
                try:
                    body = e.response.json()
                except ValueError:
                    body = {}
                message = next(
                    (body[key] for key in ("detail", "message", "error") if isinstance(body, dict) and body.get(key)),
                    None,
                )
                if not isinstance(message, str):
                    message = f"Keitaro returned HTTP {e.response.status_code}"
                raise KeitaroAPIError(
                    f"{message[:300]} (HTTP {e.response.status_code})",
                    api_status=e.response.status_code,
                ) from e
            except httpx.TimeoutException as e:
                logger.warning("Keitaro request timed out: %s %s", method, url)
                raise KeitaroAPIError("Keitaro request timed out", http_status=504) from e
            except httpx.RequestError as e:
                logger.error("Keitaro request failed: %s %s (%s)", method, url, type(e).__name__)
                raise KeitaroAPIError("Could not connect to Keitaro", http_status=502) from e
            except ValueError as e:
                logger.error("Keitaro returned invalid JSON: %s %s", method, url)
                raise KeitaroAPIError("Keitaro returned an invalid response", http_status=502) from e
            except Exception as e:
                logger.error(f"Keitaro client error: {e}")
                raise

    # ============ Campaigns ============

    async def get_campaigns(self) -> List[Dict[str, Any]]:
        """Get list of all campaigns."""
        return await self._request("GET", "/campaigns")

    async def get_campaign(self, campaign_id: int) -> Dict[str, Any]:
        """Get campaign details."""
        return await self._request("GET", f"/campaigns/{campaign_id}")

    async def create_campaign(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new campaign."""
        return await self._request("POST", "/campaigns", json=payload)

    async def delete_campaign(self, campaign_id: int) -> Dict[str, Any]:
        """Delete a campaign and its streams from the test emulator."""
        return await self._request("DELETE", f"/campaigns/{campaign_id}")

    async def update_campaign(
        self, campaign_id: int, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update campaign."""
        return await self._request("PUT", f"/campaigns/{campaign_id}", json=payload)

    # ============ Streams ============

    async def get_streams(self, campaign_id: int) -> List[Dict[str, Any]]:
        """Get all streams for a campaign."""
        return await self._request("GET", f"/campaigns/{campaign_id}/streams")

    async def get_stream(self, stream_id: int) -> Dict[str, Any]:
        """Get stream details."""
        return await self._request("GET", f"/streams/{stream_id}")

    async def create_stream(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new stream in a campaign."""
        return await self._request("POST", "/streams", json=payload)

    async def update_stream(
        self, stream_id: int, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update stream (PUT replaces entire offers list)."""
        return await self._request("PUT", f"/streams/{stream_id}", json=payload)

    # ============ Offers ============

    async def get_offers(self) -> List[Dict[str, Any]]:
        """Get list of all offers."""
        return await self._request("GET", "/offers")

    async def get_offer(self, offer_id: int) -> Dict[str, Any]:
        """Get offer details."""
        return await self._request("GET", f"/offers/{offer_id}")

    # ============ Domains ============

    async def get_domains(self) -> List[Dict[str, Any]]:
        """Get list of all domains."""
        return await self._request("GET", "/domains")

    async def get_domain(self, domain_id: int) -> Dict[str, Any]:
        """Get domain details."""
        return await self._request("GET", f"/domains/{domain_id}")

    # ============ Groups ============

    async def get_groups(self, group_type: str = "offers") -> List[Dict[str, Any]]:
        """Get list of all groups. Requires type parameter (offers, landings, redirect)."""
        return await self._request("GET", f"/groups?type={group_type}")

    async def get_group(self, group_id: int) -> Dict[str, Any]:
        """Get group details."""
        return await self._request("GET", f"/groups/{group_id}")

    # ============ Traffic Sources ============

    async def get_traffic_sources(self) -> List[Dict[str, Any]]:
        """Get list of all traffic sources."""
        return await self._request("GET", "/traffic_sources")

    async def get_traffic_source(self, source_id: int) -> Dict[str, Any]:
        """Get traffic source details."""
        return await self._request("GET", f"/traffic_sources/{source_id}")


def get_keitaro_client() -> KeitaroClient:
    """Dependency: get Keitaro client."""
    return KeitaroClient(settings.KEITARO_API_URL, settings.KEITARO_API_KEY)
