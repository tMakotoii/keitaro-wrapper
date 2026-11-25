import logging
from fastapi import APIRouter, Depends, HTTPException

from app.services.keitaro_client import KeitaroAPIError, KeitaroClient, get_keitaro_client
from app.schemas.campaign import DefaultsResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["defaults"])

# List of common GEO codes
GEO_CODES = [
    "DE", "US", "RU", "UA", "FR", "IT", "ES", "GB", "PL", "SE",
    "NO", "DK", "FI", "NL", "BE", "AT", "CH", "AU", "CA", "BR",
    "MX", "JP", "KR", "CN", "IN", "ZA", "NG", "EG", "TR", "AE",
]


@router.get("/defaults", response_model=DefaultsResponse)
async def get_defaults(
    keitaro: KeitaroClient = Depends(get_keitaro_client),
):
    """
    Get all defaults for form population:
    - offers
    - domains
    - groups
    - traffic_sources
    - geo_codes
    """
    try:
        offers = await keitaro.get_offers()
        domains = await keitaro.get_domains()
        groups = await keitaro.get_groups("campaigns")
        traffic_sources = await keitaro.get_traffic_sources()

        # Transform to expected schema
        offers_data = [
            {
                "id": o["id"],
                "name": o.get("name", f"Offer {o['id']}"),
                "group_id": o.get("group_id"),
                "state": o.get("state"),
                "country": o.get("country"),
                "payout_type": o.get("payout_type"),
                "payout_value": o.get("payout_value", 0),
                "payout_currency": o.get("payout_currency", "USD"),
                "affiliate_network_id": o.get("affiliate_network_id"),
                "offer_type": o.get("offer_type"),
                "action_type": o.get("action_type"),
            }
            for o in offers
        ]

        domains_data = [
            {
                "id": d["id"],
                "name": d.get("name"),
                "is_ssl": d.get("is_ssl", False),
                "state": d.get("state"),
            }
            for d in domains
        ]

        groups_data = [
            {
                "id": g.get("id"),
                "name": g.get("name"),
            }
            for g in groups
        ]

        traffic_sources_data = [
            {
                "id": ts.get("id"),
                "name": ts.get("name"),
            }
            for ts in traffic_sources
        ]

        return DefaultsResponse(
            offers=offers_data,
            domains=domains_data,
            groups=groups_data,
            traffic_sources=traffic_sources_data,
            geo_codes=GEO_CODES,
        )
    except KeitaroAPIError as e:
        logger.warning("Keitaro defaults request failed: %s", e)
        raise HTTPException(status_code=e.http_status, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to fetch defaults: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch defaults")
