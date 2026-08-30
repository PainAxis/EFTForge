from sqlalchemy import Column, String, Boolean, ForeignKey
from database import Base


class Slot(Base):
    __tablename__ = "slots"

    id = Column(String, primary_key=True)

    parent_item_id = Column(String, ForeignKey("items.id"), index=True)
    slot_name = Column(String)
    slot_game_name = Column(String, nullable=True)  # EFT internal slot name e.g. mod_pistol_grip
    required = Column(Boolean, default=False)  # e.g. a weapon's mandatory magazine/stock slot
