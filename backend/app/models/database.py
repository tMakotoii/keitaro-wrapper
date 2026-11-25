from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from app.config import settings

# Database engine
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class CampaignOperation(Base):
    """Audit log for campaign operations."""
    __tablename__ = "campaign_operations"

    id = Column(Integer, primary_key=True, index=True)
    operation_type = Column(String, nullable=False)  # create, add_offer, remove_offer
    campaign_id = Column(Integer, nullable=False)
    campaign_name = Column(String, nullable=False)
    user = Column(String, default="vasinovich")
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class CampaignOffer(Base):
    """Local tracking of campaign/stream/offer relations."""
    __tablename__ = "campaign_offers"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, nullable=False)
    stream_id = Column(Integer, nullable=False)
    offer_id = Column(Integer, nullable=False)
    added_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class CampaignOfferDraft(Base):
    """Pending offer changes. Keitaro remains the source of truth until apply."""
    __tablename__ = "campaign_offer_drafts"
    __table_args__ = (UniqueConstraint("campaign_id", "stream_id", "offer_id", name="uq_campaign_offer_draft"),)

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, nullable=False, index=True)
    stream_id = Column(Integer, nullable=False, index=True)
    offer_id = Column(Integer, nullable=False)
    action = Column(String, nullable=False)  # add | remove
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class CampaignOfferPin(Base):
    """Persist a wrapper-level fixed traffic share for an offer in a stream."""
    __tablename__ = "campaign_offer_pins"
    __table_args__ = (UniqueConstraint("campaign_id", "stream_id", "offer_id", name="uq_campaign_offer_pin"),)

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, nullable=False, index=True)
    stream_id = Column(Integer, nullable=False, index=True)
    offer_id = Column(Integer, nullable=False)
    share = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


def init_db():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency: get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
