from sqlalchemy import Column, String, Integer, Boolean, Text, ForeignKey
from database import Base


class ItemOffer(Base):
    """One buy option for an item - a specific trader's loyalty-level price, or a
    synthesized flea-market listing. This is additive to Item.trader_price/
    trader_vendor/etc, which stay the single cheapest-eligible-offer view every
    other page already reads. I only need this table for the optimizer's
    per-trader-level and flea-aware solving, which has to see every option to
    pick the cheapest one under a given player's trader levels, not just the
    one cheapest offer overall.

    Barter offers aren't populated yet - json.tarkov.dev (the sync source since
    the GraphQL endpoint went down) doesn't expose barter data at all. I'm
    leaving is_barter/barter_requirements in the schema so a future data source
    can fill them in without another migration.
    """

    __tablename__ = "item_offers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String, ForeignKey("items.id"), index=True)

    vendor_normalized = Column(String, index=True)  # e.g. "prapor", "flea-market"
    trader_level = Column(Integer, nullable=True)  # loyalty level 1-4; null for flea
    price = Column(Integer)
    currency = Column(String)
    price_rub = Column(Integer)

    is_flea = Column(Boolean, default=False)
    min_level_flea = Column(Integer, nullable=True)  # player account level required; flea rows only

    is_barter = Column(Boolean, default=False)
    barter_requirements = Column(Text, nullable=True)  # JSON [{"item_id": ..., "count": ...}] - unpopulated for now
