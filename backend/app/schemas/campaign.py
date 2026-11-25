from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


# ============ Filters ============

class FilterPayload(BaseModel):
    """Geo filter for streams."""
    name: str  # "country"
    mode: str  # "accept" or "reject"
    payload: List[str]  # ISO country codes, e.g., ["DE", "US"]


# ============ Offers ============

class OfferResponse(BaseModel):
    """Offer in Keitaro."""
    id: int
    name: str
    group_id: int
    state: str
    country: Optional[List[str]] = None
    payout_type: str
    payout_value: float
    payout_currency: str
    affiliate_network_id: Optional[int] = None
    offer_type: Optional[str] = None
    action_type: Optional[str] = None

    class Config:
        from_attributes = True


class OfferInStream(BaseModel):
    """Offer reference in a stream."""
    offer_id: int


# ============ Streams ============

class StreamCreate(BaseModel):
    """Create a new stream in a campaign."""
    campaign_id: int
    name: str
    type: str  # "regular" or "default"
    position: Optional[int] = None
    action_type: str  # "http"
    action_payload: str  # URL for redirect, empty for offers
    schema_: str = Field(alias="schema")  # "redirect" or "landings"
    weight: int = 100
    collect_clicks: bool = True
    filter_or: bool = False
    offer_selection: str = "before_click"
    filters: List[FilterPayload] = Field(default_factory=list)
    triggers: List[Any] = Field(default_factory=list)
    landings: List[Any] = Field(default_factory=list)
    offers: List[OfferInStream] = Field(default_factory=list)

    class Config:
        populate_by_name = True


class StreamResponse(BaseModel):
    """Stream response from Keitaro."""
    id: int
    campaign_id: int
    name: str
    type: str
    position: int
    action_type: str
    action_payload: str
    schema_: str = Field(alias="schema")
    weight: int
    collect_clicks: bool
    filter_or: bool
    offer_selection: str
    state: str
    created_at: str
    filters: List[Dict[str, Any]] = Field(default_factory=list)
    triggers: List[Any] = Field(default_factory=list)
    landings: List[Any] = Field(default_factory=list)
    offers: List[Dict[str, Any]] = Field(default_factory=list)

    class Config:
        from_attributes = True
        populate_by_name = True


# ============ Campaigns ============

class CampaignCreate(BaseModel):
    """Create a new campaign."""
    name: str = Field(min_length=1, max_length=120)
    geo: str = Field(min_length=2, max_length=2)  # ISO country code, e.g., "DE"
    offer_id: int = Field(gt=0)
    domain_id: Optional[int] = None
    group_id: int
    traffic_source_id: int


class CampaignResponse(BaseModel):
    """Campaign response from Keitaro."""
    id: int
    alias: str
    name: str
    type: str
    group_id: int
    traffic_source_id: int
    domain_id: Optional[int] = None
    state: str
    created_at: str
    updated_at: str
    group: Optional[str] = None
    domain: Optional[str] = None

    class Config:
        from_attributes = True


class CampaignWithStreams(CampaignResponse):
    """Campaign with its streams."""
    streams: List[StreamResponse] = Field(default_factory=list)


class CampaignOffers(BaseModel):
    """Campaign offers grouped by stream."""
    campaign_id: int
    campaign_name: str
    streams: List[Dict[str, Any]]
    pending_changes: bool = False
    pending_count: int = 0


# ============ Defaults ============

class Domain(BaseModel):
    """Domain in Keitaro."""
    id: int
    name: str
    is_ssl: bool
    state: str


class Group(BaseModel):
    """Group in Keitaro."""
    id: int
    name: str


class TrafficSource(BaseModel):
    """Traffic source in Keitaro."""
    id: int
    name: str


class DefaultsResponse(BaseModel):
    """All defaults for form population."""
    offers: List[OfferResponse]
    domains: List[Domain]
    groups: List[Group]
    traffic_sources: List[TrafficSource]
    geo_codes: List[str]


# ============ API Responses ============

class CreateCampaignResponse(BaseModel):
    """Response after creating a campaign."""
    campaign_id: int
    campaign_name: str
    alias: str
    streams: List[StreamResponse]
    message: str


class AddOfferResponse(BaseModel):
    """Response after staging an offer addition."""
    success: bool
    stream_id: int
    campaign_id: int
    offers: List[Dict[str, Any]]
    staged: bool = True


class RemoveOfferResponse(BaseModel):
    """Response after staging an offer removal."""
    success: bool
    removed_from: List[int]
    campaign_id: int
    staged: bool = True


class ErrorResponse(BaseModel):
    """Error response."""
    error: str
    detail: Optional[str] = None
