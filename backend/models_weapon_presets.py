from sqlalchemy import Column, String

from database import Base


class WeaponDefaultPreset(Base):
    """Maps a weapon (base receiver item id) to its default factory-preset item id.

    tarkov.dev exposes the default preset as a separate purchasable item (its own
    buyFor offers live in item_offers just like any other item), but the weapon row
    only stores the preset's contained parts (factory_attachment_ids), not the preset
    item's own id. This tiny side table records that id so the optimizer can price the
    factory configuration as an alternative base to the bare receiver.
    """

    __tablename__ = "weapon_default_presets"

    weapon_id = Column(String, primary_key=True, index=True)
    preset_id = Column(String, nullable=False)
