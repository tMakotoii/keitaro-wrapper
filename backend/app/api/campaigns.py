import logging
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.services.keitaro_client import KeitaroAPIError, KeitaroClient, get_keitaro_client
from app.services.campaign_service import CampaignService, PartialCampaignCreationError
from app.models.database import get_db
from app.models.database import CampaignOffer, CampaignOfferDraft, CampaignOfferPin, CampaignOperation
from app.schemas.campaign import (
    CampaignCreate,
    CreateCampaignResponse,
    AddOfferResponse,
    RemoveOfferResponse,
    CampaignResponse,
    CampaignWithStreams,
    CampaignOffers,
    ErrorResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["campaigns"])


# ============ Campaign Creator ============


@router.post(
    "/campaigns",
    response_model=CreateCampaignResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def create_campaign(
    req: CampaignCreate,
    keitaro: KeitaroClient = Depends(get_keitaro_client),
    db: Session = Depends(get_db),
):
    """
    Create a new campaign with two streams:
    1. Redirect to Google (filtered by GEO)
    2. Target offer stream
    """
    try:
        service = CampaignService(keitaro, db)
        result = await service.create_campaign(req)
        return result
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except PartialCampaignCreationError as e:
        logger.exception("Campaign setup failed after partial creation")
        raise HTTPException(status_code=502, detail=str(e)) from e
    except KeitaroAPIError as e:
        logger.error("Keitaro campaign creation request failed: %s", e)
        raise HTTPException(status_code=e.http_status, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to create campaign: {e}")
        raise HTTPException(status_code=500, detail="Failed to create campaign")


# ============ Campaign Editor ============


@router.get("/campaigns", response_model=list[CampaignResponse])
async def list_campaigns(
    keitaro: KeitaroClient = Depends(get_keitaro_client),
):
    """Get list of all campaigns."""
    try:
        campaigns = await keitaro.get_campaigns()
        return campaigns
    except KeitaroAPIError as e:
        logger.warning("Keitaro campaign list request failed: %s", e)
        raise HTTPException(status_code=e.http_status, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to fetch campaigns: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch campaigns")


@router.get("/campaigns/{campaign_id}", response_model=CampaignWithStreams)
async def get_campaign_detail(
    campaign_id: int,
    keitaro: KeitaroClient = Depends(get_keitaro_client),
):
    """Get campaign details with streams."""
    try:
        campaign = await keitaro.get_campaign(campaign_id)
        streams = await keitaro.get_streams(campaign_id)
        if isinstance(streams, dict):
            streams = streams.get("streams", streams.get("data", []))
        if not isinstance(streams, list):
            raise ValueError("Unexpected streams response from Keitaro")
        campaign["streams"] = streams
        return campaign
    except KeitaroAPIError as e:
        logger.warning("Keitaro campaign detail request failed for %s: %s", campaign_id, e)
        raise HTTPException(status_code=e.http_status, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to fetch campaign {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch campaign")


@router.get("/campaigns/{campaign_id}/offers", response_model=CampaignOffers)
async def get_campaign_offers(
    campaign_id: int,
    keitaro: KeitaroClient = Depends(get_keitaro_client),
    db: Session = Depends(get_db),
):
    """Get all offers in campaign grouped by stream."""
    try:
        streams = await keitaro.get_streams(campaign_id)
        if isinstance(streams, dict):
            streams = streams.get("streams", streams.get("data", []))
        if not isinstance(streams, list):
            raise ValueError("Unexpected streams response from Keitaro")

        drafts = db.query(CampaignOfferDraft).filter_by(campaign_id=campaign_id).all()
        pins = db.query(CampaignOfferPin).filter_by(campaign_id=campaign_id).all()
        pins_by_stream: dict[int, dict[int, int]] = {}
        for pin in pins:
            pins_by_stream.setdefault(pin.stream_id, {})[pin.offer_id] = pin.share
        drafts_by_stream: dict[int, dict[int, str]] = {}
        for draft in drafts:
            drafts_by_stream.setdefault(draft.stream_id, {})[draft.offer_id] = draft.action

        history_by_stream: dict[int, set[int]] = {}
        for relation in db.query(CampaignOffer).filter_by(campaign_id=campaign_id).all():
            history_by_stream.setdefault(relation.stream_id, set()).add(relation.offer_id)

        # Rebuild historical relations from the audit log as older app versions
        # deleted local campaign_offers rows after removing an offer in Keitaro.
        for operation in db.query(CampaignOperation).filter_by(campaign_id=campaign_id).all():
            details = operation.details or {}
            offer_id = details.get("offer_id")
            if offer_id is None:
                continue
            stream_ids = []
            if details.get("stream_id") is not None:
                stream_ids.append(details["stream_id"])
            if details.get("stream2_id") is not None:
                stream_ids.append(details["stream2_id"])
            stream_ids.extend(details.get("removed_from_streams", []))
            for historical_stream_id in stream_ids:
                history_by_stream.setdefault(int(historical_stream_id), set()).add(int(offer_id))

        # Group streams with their offers
        streams_data = []
        pending_streams = 0
        for stream in streams:
            if not isinstance(stream, dict) or stream.get("id") is None:
                logger.warning("Skipping malformed stream for campaign %s", campaign_id)
                continue
            is_landings = stream.get("schema") == "landings"
            stream_id = int(stream["id"])
            stream_drafts = drafts_by_stream.get(stream_id, {})
            offers = [dict(offer) for offer in stream.get("offers", [])]
            current_ids = {int(offer.get("offer_id", -1)) for offer in offers}
            known_ids = history_by_stream.setdefault(stream_id, set())
            for offer_id in current_ids:
                if offer_id >= 0 and offer_id not in known_ids:
                    db.add(CampaignOffer(campaign_id=campaign_id, stream_id=stream_id, offer_id=offer_id))
                    known_ids.add(offer_id)
            for offer in offers:
                action = stream_drafts.get(int(offer.get("offer_id", -1)))
                if action:
                    offer["draft_action"] = action
            for offer_id, action in stream_drafts.items():
                if action == "add" and offer_id not in current_ids:
                    offers.append({"offer_id": offer_id, "state": "active", "draft_action": "add"})
                elif action == "remove" and offer_id not in current_ids:
                    offers.append({"offer_id": offer_id, "state": "active", "draft_action": "remove"})
            for offer_id in sorted(known_ids - current_ids - set(stream_drafts)):
                offers.append({"offer_id": offer_id, "state": "missing", "draft_action": "missing"})

            stream_pins = pins_by_stream.get(stream_id, {})
            for offer in offers:
                pinned_share = stream_pins.get(int(offer.get("offer_id", -1)))
                offer["pinned"] = pinned_share is not None
                if pinned_share is not None:
                    offer["pinned_share"] = pinned_share

            share_pending = False
            share_error = None
            if is_landings and (stream_drafts or stream_pins):
                current_shares = {
                    int(offer["offer_id"]): offer.get("share")
                    for offer in offers
                    if offer.get("offer_id") is not None and offer.get("draft_action") not in {"add", "missing"}
                }
                try:
                    desired_shares = CampaignService.allocate_shares(offers, stream_pins)
                    for offer in offers:
                        offer_id = offer.get("offer_id")
                        if offer_id is not None and int(offer_id) in desired_shares:
                            offer["share"] = desired_shares[int(offer_id)]
                    share_pending = any(current_shares.get(offer_id) != share for offer_id, share in desired_shares.items() if offer_id in current_shares)
                except ValueError as exc:
                    share_error = str(exc)
            has_pending_changes = bool(stream_drafts) or share_pending
            if has_pending_changes:
                pending_streams += 1
            streams_data.append(
                {
                    "stream_id": stream_id,
                    "stream_name": stream.get("name") or f"Stream {stream_id}",
                    "schema": stream.get("schema"),
                    "type": stream.get("type"),
                    "offers": offers,
                    "can_edit": is_landings,  # Only landings streams can be edited
                    "has_pending_changes": has_pending_changes,
                    "share_pending": share_pending,
                    "share_error": share_error,
                }
            )

        db.commit()

        return {
            "campaign_id": campaign_id,
            "campaign_name": f"Campaign {campaign_id}",
            "streams": streams_data,
            "pending_changes": bool(drafts) or pending_streams > 0,
            "pending_count": len(drafts) + max(0, pending_streams - len({draft.stream_id for draft in drafts})),
        }
    except KeitaroAPIError as e:
        logger.exception("Keitaro returned an error loading campaign %s streams", campaign_id)
        raise HTTPException(
            status_code=e.http_status,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.exception("Failed to fetch offers for campaign %s", campaign_id)
        raise HTTPException(
            status_code=502,
            detail="Keitaro returned an unexpected stream response. Retry or check the server log.",
        ) from e


@router.post(
    "/campaigns/{campaign_id}/offers",
    response_model=AddOfferResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def add_offer_to_campaign(
    campaign_id: int,
    offer_id: int,
    stream_id: int | None = Query(None),
    keitaro: KeitaroClient = Depends(get_keitaro_client),
    db: Session = Depends(get_db),
):
    """Add offer to campaign stream."""
    try:
        service = CampaignService(keitaro, db)
        result = await service.add_offer_to_campaign(campaign_id, offer_id, stream_id)
        return result
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except KeitaroAPIError as e:
        logger.warning("Keitaro add-offer request failed: %s", e)
        raise HTTPException(status_code=e.http_status, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to add offer: {e}")
        raise HTTPException(status_code=500, detail="Failed to add offer")


@router.delete(
    "/campaigns/{campaign_id}/offers/{offer_id}",
    response_model=RemoveOfferResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def remove_offer_from_campaign(
    campaign_id: int,
    offer_id: int,
    stream_id: int | None = Query(None),
    keitaro: KeitaroClient = Depends(get_keitaro_client),
    db: Session = Depends(get_db),
):
    """Remove offer from campaign stream."""
    try:
        service = CampaignService(keitaro, db)
        result = await service.remove_offer_from_campaign(
            campaign_id, offer_id, stream_id
        )
        return result
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except KeitaroAPIError as e:
        logger.warning("Keitaro remove-offer request failed: %s", e)
        raise HTTPException(status_code=e.http_status, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to remove offer: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove offer")


@router.post("/campaigns/{campaign_id}/offers/{offer_id}/restore")
async def restore_staged_offer(
    campaign_id: int,
    offer_id: int,
    stream_id: int = Query(...),
    keitaro: KeitaroClient = Depends(get_keitaro_client),
    db: Session = Depends(get_db),
):
    """Restore an offer by discarding its pending change."""
    try:
        return await CampaignService(keitaro, db).restore_offer(campaign_id, stream_id, offer_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except KeitaroAPIError as e:
        logger.warning("Keitaro restore-offer request failed: %s", e)
        raise HTTPException(status_code=e.http_status, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to restore staged offer")
        raise HTTPException(status_code=500, detail="Failed to restore offer") from e


@router.post("/campaigns/{campaign_id}/streams/{stream_id}/offers/{offer_id}/pin")
async def pin_offer_share(
    campaign_id: int,
    stream_id: int,
    offer_id: int,
    share: int = Body(..., embed=True, ge=0, le=100),
    keitaro: KeitaroClient = Depends(get_keitaro_client),
    db: Session = Depends(get_db),
):
    """Pin the offer's current share locally; send it to Keitaro on apply."""
    try:
        return await CampaignService(keitaro, db).set_offer_pin(campaign_id, stream_id, offer_id, share)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except KeitaroAPIError as e:
        raise HTTPException(status_code=e.http_status, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to pin offer share")
        raise HTTPException(status_code=500, detail="Failed to pin offer share") from e


@router.delete("/campaigns/{campaign_id}/streams/{stream_id}/offers/{offer_id}/pin")
async def unpin_offer_share(
    campaign_id: int,
    stream_id: int,
    offer_id: int,
    keitaro: KeitaroClient = Depends(get_keitaro_client),
    db: Session = Depends(get_db),
):
    """Unpin an offer share locally; the rebalanced result is sent on apply."""
    try:
        return await CampaignService(keitaro, db).set_offer_pin(campaign_id, stream_id, offer_id, None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except KeitaroAPIError as e:
        raise HTTPException(status_code=e.http_status, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to unpin offer share")
        raise HTTPException(status_code=500, detail="Failed to unpin offer share") from e


@router.post("/campaigns/{campaign_id}/offers/apply")
async def apply_staged_offers(
    campaign_id: int,
    keitaro: KeitaroClient = Depends(get_keitaro_client),
    db: Session = Depends(get_db),
):
    """Apply the campaign's staged offer changes to Keitaro."""
    try:
        return await CampaignService(keitaro, db).apply_offer_changes(campaign_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except KeitaroAPIError as e:
        logger.warning("Keitaro apply-offer request failed: %s", e)
        raise HTTPException(status_code=e.http_status, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to apply staged offer changes for campaign %s", campaign_id)
        raise HTTPException(status_code=502, detail="Keitaro did not accept the staged changes") from e
