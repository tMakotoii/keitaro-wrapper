import logging
import uuid
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.services.keitaro_client import KeitaroAPIError, KeitaroClient
from app.schemas.campaign import CampaignCreate
from app.models.database import CampaignOperation, CampaignOffer, CampaignOfferDraft, CampaignOfferPin

logger = logging.getLogger(__name__)


class PartialCampaignCreationError(RuntimeError):
    """Campaign setup failed after Keitaro had already created resources."""

    def __init__(self, campaign_id: int, step: str, cause: Exception, cleanup_errors: List[str]):
        self.campaign_id = campaign_id
        self.step = step
        cleanup_note = (
            f" Cleanup also failed: {'; '.join(cleanup_errors)}"
            if cleanup_errors
            else " The partially created campaign was deleted."
        )
        super().__init__(f"Campaign #{campaign_id} setup failed while {step}: {cause}.{cleanup_note}")


class CampaignService:
    """Business logic for campaign management."""

    def __init__(self, keitaro_client: KeitaroClient, db: Session):
        self.client = keitaro_client
        self.db = db

    async def create_campaign(self, req: CampaignCreate) -> Dict[str, Any]:
        """
        Create a campaign with two streams:
        1. Redirect to Google (filtered by GEO)
        2. Target offer stream
        """
        # Validate offer exists
        try:
            await self.client.get_offer(req.offer_id)
        except KeitaroAPIError as e:
            if e.api_status == 404:
                raise ValueError(f"Offer {req.offer_id} does not exist") from e
            logger.exception("Keitaro failed while validating offer %s", req.offer_id)
            raise
        except Exception:
            logger.exception("Keitaro request failed while validating offer %s", req.offer_id)
            raise

        # Generate unique alias
        alias = f"test_{uuid.uuid4().hex[:12]}"
        campaign_name = f"test_{req.name.strip().rstrip('_')}"

        # Create campaign
        campaign_payload = {
            "name": campaign_name,
            "alias": alias,
            "type": "position",
            "group_id": req.group_id,
            "traffic_source_id": req.traffic_source_id,
        }
        if req.domain_id is not None:
            campaign_payload["domain_id"] = req.domain_id

        try:
            campaign = await self.client.create_campaign(campaign_payload)
            campaign_id = campaign["id"]
            logger.info(f"Campaign created: {campaign_id} (alias: {alias})")
        except Exception as e:
            logger.error(f"Failed to create campaign: {e}")
            raise

        # Create Stream 1: Redirect to Google (filtered by GEO)
        stream1_payload = {
            "campaign_id": campaign_id,
            "name": f"{req.geo} → Google",
            "type": "regular",
            "position": 1,
            "action_type": "http",
            "action_payload": "https://www.google.com/",
            "schema": "redirect",
            "weight": 100,
            "collect_clicks": True,
            "filter_or": False,
            "offer_selection": "before_click",
            "filters": [
                {
                    "name": "country",
                    "mode": "accept",
                    "payload": [req.geo],
                }
            ],
            "triggers": [],
            "landings": [],
            "offers": [],
        }

        try:
            stream1 = await self.client.create_stream(stream1_payload)
            stream1_id = stream1["id"]
            logger.info(f"Stream 1 created: {stream1_id} (redirect)")
        except Exception as e:
            logger.error(f"Failed to create Stream 1: {e}")
            cleanup_errors = await self._delete_partial_campaign(campaign_id)
            raise PartialCampaignCreationError(campaign_id, "creating the redirect stream", e, cleanup_errors) from e

        # Create Stream 2: Target offer (no filters)
        stream2_payload = {
            "campaign_id": campaign_id,
            "name": "Main Offer",
            "type": "default",
            "position": 2,
            "action_type": "http",
            "action_payload": "",
            "schema": "landings",
            "weight": 100,
            "collect_clicks": True,
            "filter_or": False,
            "offer_selection": "before_click",
            "filters": [],
            "triggers": [],
            "landings": [],
            "offers": [{"offer_id": req.offer_id, "share": 100, "state": "active"}],
        }

        try:
            stream2 = await self.client.create_stream(stream2_payload)
            stream2_id = stream2["id"]
            logger.info(f"Stream 2 created: {stream2_id} (offer)")
        except Exception as e:
            logger.error(f"Failed to create Stream 2: {e}")
            cleanup_errors = await self._delete_partial_campaign(campaign_id)
            raise PartialCampaignCreationError(campaign_id, "creating the offer stream", e, cleanup_errors) from e

        try:
            self.db.add(CampaignOperation(
                operation_type="create",
                campaign_id=campaign_id,
                campaign_name=campaign["name"],
                user="local",
                details={
                    "alias": alias,
                    "geo": req.geo,
                    "offer_id": req.offer_id,
                    "stream1_id": stream1_id,
                    "stream2_id": stream2_id,
                },
            ))
            self.db.add(CampaignOffer(campaign_id=campaign_id, stream_id=stream2_id, offer_id=req.offer_id))
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            cleanup_errors = await self._delete_partial_campaign(campaign_id)
            raise PartialCampaignCreationError(campaign_id, "recording the local audit log", e, cleanup_errors) from e

        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign["name"],
            "alias": alias,
            "streams": [stream1, stream2],
            "message": f"Campaign '{alias}' created successfully with 2 streams",
        }

    async def add_offer_to_campaign(
        self, campaign_id: int, offer_id: int, stream_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Stage an addition locally. Keitaro is not changed until apply_offer_changes."""
        await self._validate_offer(offer_id)
        _, stream = await self._get_editable_stream(campaign_id, stream_id)
        existing = self._get_draft(campaign_id, stream["id"], offer_id)
        current_ids = {int(item.get("offer_id", -1)) for item in stream.get("offers", [])}

        if offer_id in current_ids:
            if existing and existing.action == "remove":
                self.db.delete(existing)
                self.db.commit()
                return {"success": True, "stream_id": stream["id"], "campaign_id": campaign_id, "offers": stream.get("offers", [])}
            raise ValueError(f"Offer {offer_id} already exists in this stream")
        if existing and existing.action == "add":
            raise ValueError(f"Offer {offer_id} is already staged for this stream")

        self.db.add(CampaignOfferDraft(campaign_id=campaign_id, stream_id=stream["id"], offer_id=offer_id, action="add"))
        self.db.commit()
        return {"success": True, "stream_id": stream["id"], "campaign_id": campaign_id, "offers": stream.get("offers", [])}

    async def remove_offer_from_campaign(
        self, campaign_id: int, offer_id: int, stream_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Stage a removal locally. The live offer remains in Keitaro until apply."""
        _, stream = await self._get_editable_stream(campaign_id, stream_id)
        draft = self._get_draft(campaign_id, stream["id"], offer_id)
        if draft and draft.action == "add":
            self.db.delete(draft)  # cancel an addition that has not reached Keitaro
            self.db.commit()
            return {"success": True, "removed_from": [stream["id"]], "campaign_id": campaign_id}
        current_ids = {int(item.get("offer_id", -1)) for item in stream.get("offers", [])}
        if offer_id not in current_ids:
            raise ValueError(f"Offer {offer_id} not found in stream {stream['id']}")
        if not draft:
            self.db.add(CampaignOfferDraft(campaign_id=campaign_id, stream_id=stream["id"], offer_id=offer_id, action="remove"))
            self.db.commit()
        return {"success": True, "removed_from": [stream["id"]], "campaign_id": campaign_id}

    async def restore_offer(self, campaign_id: int, stream_id: int, offer_id: int) -> Dict[str, Any]:
        """Undo a staged removal or stage a previously seen, externally removed offer."""
        _, stream = await self._get_editable_stream(campaign_id, stream_id)
        draft = self._get_draft(campaign_id, stream_id, offer_id)
        if draft:
            if draft.action != "remove":
                raise ValueError("This offer is not waiting to be restored")
            self.db.delete(draft)
            self.db.commit()
            return {"success": True, "campaign_id": campaign_id, "stream_id": stream_id, "offer_id": offer_id, "action": "restored"}

        history = self.db.query(CampaignOffer).filter_by(
            campaign_id=campaign_id, stream_id=stream_id, offer_id=offer_id
        ).first()
        if not history:
            for operation in self.db.query(CampaignOperation).filter_by(campaign_id=campaign_id).all():
                details = operation.details or {}
                if int(details.get("offer_id", -1)) != offer_id:
                    continue
                historical_stream_ids = [
                    value for value in (details.get("stream_id"), details.get("stream2_id"))
                    if value is not None
                ]
                historical_stream_ids.extend(details.get("removed_from_streams", []))
                if stream_id in {int(value) for value in historical_stream_ids}:
                    history = True
                    break
        if not history:
            raise ValueError("This offer has not previously been in the stream")
        current_ids = {int(item.get("offer_id", -1)) for item in stream.get("offers", [])}
        if offer_id in current_ids:
            raise ValueError("Offer is already in Keitaro")
        await self._validate_offer(offer_id)
        self.db.add(CampaignOfferDraft(campaign_id=campaign_id, stream_id=stream_id, offer_id=offer_id, action="add"))
        self.db.commit()
        return {"success": True, "campaign_id": campaign_id, "stream_id": stream_id, "offer_id": offer_id, "action": "add_staged"}

    async def set_offer_pin(
        self, campaign_id: int, stream_id: int, offer_id: int, share: Optional[int]
    ) -> Dict[str, Any]:
        """Pin an offer's current displayed share, or clear its pin when share is None."""
        _, stream = await self._get_editable_stream(campaign_id, stream_id)
        drafts = self.db.query(CampaignOfferDraft).filter_by(campaign_id=campaign_id, stream_id=stream_id).all()
        drafts_by_offer = {draft.offer_id: draft.action for draft in drafts}
        live_offers = {int(item["offer_id"]): dict(item) for item in stream.get("offers", []) if item.get("offer_id") is not None}
        candidates = list(live_offers.values())
        for pending_offer_id, action in drafts_by_offer.items():
            if action == "remove":
                candidates = [item for item in candidates if int(item["offer_id"]) != pending_offer_id]
            elif action == "add" and pending_offer_id not in live_offers:
                candidates.append({"offer_id": pending_offer_id, "state": "active"})

        offer_is_active = any(
            int(item["offer_id"]) == offer_id and item.get("state", "active") != "disabled"
            for item in candidates
        )
        if share is not None and not offer_is_active:
            raise ValueError("Only an active offer in this stream can be pinned")

        existing_pins = self.db.query(CampaignOfferPin).filter_by(campaign_id=campaign_id, stream_id=stream_id).all()
        pin_by_offer = {pin.offer_id: pin for pin in existing_pins}
        if share is None:
            pin = pin_by_offer.get(offer_id)
            if pin:
                self.db.delete(pin)
        else:
            pin = pin_by_offer.get(offer_id)
            if pin:
                pin.share = share
            else:
                self.db.add(CampaignOfferPin(campaign_id=campaign_id, stream_id=stream_id, offer_id=offer_id, share=share))
            pin_shares = {offer_id: share}
            pin_shares.update({item.offer_id: item.share for item in existing_pins if item.offer_id != offer_id})
            self.allocate_shares(candidates, pin_shares)

        self.db.commit()
        return {"success": True, "campaign_id": campaign_id, "stream_id": stream_id, "offer_id": offer_id, "pinned": share is not None, "share": share}

    @staticmethod
    def allocate_shares(offers: List[Dict[str, Any]], pinned_shares: Dict[int, int]) -> Dict[int, int]:
        """Keep pinned shares fixed and split the remaining integer percentage equally."""
        active = [
            offer for offer in offers
            if offer.get("state", "active") != "disabled"
            and offer.get("state") != "missing"
            and offer.get("draft_action") != "remove"
        ]
        active_ids = {int(offer["offer_id"]) for offer in active}
        pins = {offer_id: share for offer_id, share in pinned_shares.items() if offer_id in active_ids}
        pinned_total = sum(pins.values())
        if pinned_total > 100:
            raise ValueError("Закреплённые доли не могут превышать 100% трафика")
        unpinned = [offer_id for offer_id in active_ids if offer_id not in pins]
        if not unpinned:
            if active and pinned_total != 100:
                raise ValueError("Когда закреплены все офферы, сумма их долей должна быть ровно 100%")
            return pins
        remaining = 100 - pinned_total
        quotient, remainder = divmod(remaining, len(unpinned))
        result = dict(pins)
        for index, offer_id in enumerate(sorted(unpinned)):
            result[offer_id] = quotient + (1 if index < remainder else 0)
        return result

    async def apply_offer_changes(self, campaign_id: int) -> Dict[str, Any]:
        """Apply all staged changes, replacing complete offers arrays per stream."""
        campaign = await self.client.get_campaign(campaign_id)
        drafts = self.db.query(CampaignOfferDraft).filter(CampaignOfferDraft.campaign_id == campaign_id).all()
        pins = self.db.query(CampaignOfferPin).filter_by(campaign_id=campaign_id).all()
        if not drafts and not pins:
            return {"success": True, "campaign_id": campaign_id, "applied": 0, "streams": []}

        streams = await self.client.get_streams(campaign_id)
        if isinstance(streams, dict):
            streams = streams.get("streams", streams.get("data", []))
        by_id = {int(s["id"]): s for s in streams if isinstance(s, dict) and s.get("id") is not None}
        grouped: Dict[int, List[CampaignOfferDraft]] = {}
        for draft in drafts:
            grouped.setdefault(draft.stream_id, []).append(draft)
        pins_by_stream: Dict[int, Dict[int, int]] = {}
        for pin in pins:
            pins_by_stream.setdefault(pin.stream_id, {})[pin.offer_id] = pin.share
        target_stream_ids = set(grouped) | set(pins_by_stream)

        applied_details = []
        for target_id in target_stream_ids:
            stream_drafts = grouped.get(target_id, [])
            summary = by_id.get(target_id)
            if not summary or summary.get("schema") != "landings":
                raise ValueError(f"Editable stream {target_id} no longer exists in campaign {campaign_id}")
            stream = await self.client.get_stream(target_id)
            offers_by_id = {int(item["offer_id"]): dict(item) for item in stream.get("offers", []) if item.get("offer_id") is not None}
            for draft in stream_drafts:
                if draft.action == "add":
                    offers_by_id.setdefault(draft.offer_id, {"offer_id": draft.offer_id, "state": "active"})
                elif draft.action == "remove":
                    offers_by_id.pop(draft.offer_id, None)

            offers = list(offers_by_id.values())
            assigned_shares = self.allocate_shares(offers, pins_by_stream.get(target_id, {}))
            for offer in offers:
                if int(offer["offer_id"]) in assigned_shares:
                    offer["share"] = assigned_shares[int(offer["offer_id"])]
            request_offers = [
                {"offer_id": item["offer_id"], "share": int(item.get("share", 0)), **({"state": item["state"]} if item.get("state") in {"active", "disabled"} else {})}
                for item in offers
            ]
            original_offers = stream.get("offers", [])
            shares_changed = any(
                assigned_shares.get(int(item.get("offer_id", -1))) != item.get("share")
                for item in original_offers
            )
            if stream_drafts or shares_changed:
                payload = self._stream_update_payload(stream, request_offers)
                await self.client.update_stream(target_id, payload)
                applied_details.append({"stream_id": target_id, "offers": request_offers})

        # Record successful changes and clear the draft atomically in the local DB.
        for draft in drafts:
            self.db.add(CampaignOperation(
                operation_type="add_offer" if draft.action == "add" else "remove_offer",
                campaign_id=campaign_id,
                campaign_name=campaign.get("name", f"Campaign {campaign_id}"),
                user="local",
                details={"stream_id": draft.stream_id, "offer_id": draft.offer_id, "equal_share_applied": True},
            ))
            if draft.action == "add":
                self._add_campaign_offer_without_commit(campaign_id, draft.stream_id, draft.offer_id)
            self.db.delete(draft)
        self.db.commit()
        return {"success": True, "campaign_id": campaign_id, "applied": len(drafts), "updated_streams": len(applied_details), "streams": applied_details}

    async def _validate_offer(self, offer_id: int) -> None:
        try:
            await self.client.get_offer(offer_id)
        except KeitaroAPIError as exc:
            if exc.api_status == 404:
                raise ValueError(f"Offer {offer_id} does not exist") from exc
            raise

    async def _delete_partial_campaign(self, campaign_id: int) -> List[str]:
        """Best-effort rollback; the test emulator permanently deletes campaigns."""
        try:
            await self.client.delete_campaign(campaign_id)
        except Exception as exc:
            logger.exception("Could not delete partially created campaign %s", campaign_id)
            return [f"campaign {campaign_id}: {exc}"]
        return []

    async def _get_editable_stream(self, campaign_id: int, stream_id: Optional[int]):
        campaign = await self.client.get_campaign(campaign_id)
        streams = await self.client.get_streams(campaign_id)
        if isinstance(streams, dict):
            streams = streams.get("streams", streams.get("data", []))
        stream = next((item for item in streams if item.get("id") == stream_id), None) if stream_id is not None else next((item for item in streams if item.get("schema") == "landings"), None)
        if not stream:
            raise ValueError(f"Stream {stream_id} not found in campaign" if stream_id is not None else "No landings stream found in campaign")
        if stream.get("schema") != "landings":
            raise ValueError("Only landings streams can be edited")
        return campaign, stream

    def _get_draft(self, campaign_id: int, stream_id: int, offer_id: int):
        return self.db.query(CampaignOfferDraft).filter_by(campaign_id=campaign_id, stream_id=stream_id, offer_id=offer_id).first()

    @staticmethod
    def _stream_update_payload(stream: Dict[str, Any], offers: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "campaign_id": stream["campaign_id"], "name": stream["name"], "type": stream["type"],
            "position": stream.get("position"), "weight": stream.get("weight", 100),
            "action_type": stream["action_type"], "action_payload": stream.get("action_payload", ""),
            "schema": stream["schema"], "collect_clicks": stream.get("collect_clicks", True),
            "filter_or": stream.get("filter_or", False), "offer_selection": stream.get("offer_selection", "before_click"),
            "filters": stream.get("filters", []), "triggers": stream.get("triggers", []),
            "landings": stream.get("landings", []), "offers": offers,
            **({"state": stream["state"]} if stream.get("state") else {}),
            **({"comments": stream["comments"]} if stream.get("comments") is not None else {}),
            **({"action_options": stream["action_options"]} if stream.get("action_options") is not None else {}),
        }

    def _add_campaign_offer_without_commit(self, campaign_id: int, stream_id: int, offer_id: int) -> None:
        existing = self.db.query(CampaignOffer).filter_by(campaign_id=campaign_id, stream_id=stream_id, offer_id=offer_id).first()
        if not existing:
            self.db.add(CampaignOffer(campaign_id=campaign_id, stream_id=stream_id, offer_id=offer_id))
