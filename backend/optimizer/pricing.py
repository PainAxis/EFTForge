"""Picks the cheapest accessible offer for an item given trader loyalty levels,
flea access, and player level - ported from the reference optimizer's
get_available_price(), reading from EFTForge's own item_offers table instead
of a tarkov.dev-shaped offers list.
"""

DEFAULT_TRADER_LEVELS = {
    "prapor": 4,
    "skier": 4,
    "peacekeeper": 4,
    "mechanic": 4,
    "jaeger": 4,
    "ragman": 4,
    "ref": 4,
}

TRADER_DISABLED = 0


def get_best_price(offers: list, trader_levels: dict = None, flea_available: bool = True, player_level=None):
    """offers: list of dicts with vendor_normalized, trader_level, price, currency,
    price_rub, is_flea, min_level_flea (the shape produced by loading ItemOffer rows).

    Returns a dict {price, currency, price_rub, vendor} for the cheapest offer the
    given player can actually access right now, or None if nothing is accessible.
    """
    if trader_levels is None:
        trader_levels = DEFAULT_TRADER_LEVELS

    best = None
    for offer in offers:
        if offer["is_flea"]:
            if not flea_available:
                continue
            min_level_flea = offer.get("min_level_flea")
            if player_level is not None and min_level_flea and min_level_flea > player_level:
                continue
        else:
            vendor = offer["vendor_normalized"]
            level = trader_levels.get(vendor, 4)
            if level == TRADER_DISABLED:
                continue
            required_level = offer.get("trader_level")
            if required_level is not None and required_level > level:
                continue

        price_rub = offer.get("price_rub")
        if price_rub is None:
            continue
        if best is None or price_rub < best["price_rub"]:
            best = {
                "price": offer.get("price"),
                "currency": offer.get("currency"),
                "price_rub": price_rub,
                "vendor": offer["vendor_normalized"],
            }

    return best


def offers_by_item(item_offer_rows) -> dict:
    """Groups ItemOffer ORM rows into item_id -> [offer dict, ...]."""
    grouped: dict = {}
    for row in item_offer_rows:
        grouped.setdefault(row.item_id, []).append(
            {
                "vendor_normalized": row.vendor_normalized,
                "trader_level": row.trader_level,
                "price": row.price,
                "currency": row.currency,
                "price_rub": row.price_rub,
                "is_flea": row.is_flea,
                "min_level_flea": row.min_level_flea,
            }
        )
    return grouped
