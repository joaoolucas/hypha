"""Seed registries: labeled addresses to exclude from holder analysis, and launchpad
signatures for Feature 6. In production these live in Postgres (`labeled_addresses`,
`launchpad_signatures`) and are curated over time — this module is the bootstrap seed.

⚠️ Items marked UNVERIFIED must be filled from on-chain labels (Tonviewer) before relied on.
"""

from __future__ import annotations

# Verified burn address (blockburner.ton) — both friendly and raw forms.
BURN_ADDRESSES: set[str] = {
    "UQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJKZ",
    "EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM",
    "0:0000000000000000000000000000000000000000000000000000000000000000",
}

# Substrings in a holder's on-chain label (TonAPI owner.name) that mean "not a real holder":
# DEX pools/routers/vaults and liquidity lockers hold supply backing liquidity, not whales.
EXCLUDE_LABEL_KEYWORDS: tuple[str, ...] = (
    "ston.fi", "stonfi", "dedust", "vault", "pool", "router", "liquidity",
    "locker", "lock", "burn", "megaton", "tonco",
)

# Launchpad detection. MVP heuristic = metadata/symbol patterns + (later) code-hash match.
# graduation_dex drives both Feature 6 and the buy-router.
LAUNCHPAD_SIGNATURES: dict[str, dict] = {
    "gaspump": {
        "label": "GasPump",
        "symbol_prefixes": ("gas",),          # wrapped $gasXXX jettons
        "name_keywords": ("gaspump",),
        "graduation_dex": "dedust",
        "reputable": True,
        # "code_hash": "UNVERIFIED — derive via @gaspump/sdk GaspumpJetton",
    },
    "blum": {
        "label": "Blum Memepad",
        "symbol_prefixes": (),
        "name_keywords": ("blum",),
        "graduation_dex": "stonfi",
        "reputable": True,
    },
    "tonup": {
        "label": "TonUP",
        "symbol_prefixes": (),
        "name_keywords": ("tonup",),
        "graduation_dex": "stonfi",
        "reputable": True,
    },
}


def is_excluded_label(label: str | None) -> bool:
    if not label:
        return False
    low = label.lower()
    return any(k in low for k in EXCLUDE_LABEL_KEYWORDS)
