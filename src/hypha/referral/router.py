"""Buy-router: pick the venue from the token's launch/DEX status, tag it with our referral,
and optionally wrap it in the first-party redirect service for click attribution.

  on-curve (gaspump/blum) -> launchpad buy page
  graduated / listed       -> swap.coffee (aggregator) or STON.fi referral link
DeDust has no referral URL (SDK-only) so DeDust-only tokens route via swap.coffee/STON.fi.
See SPEC.md §6.
"""

from __future__ import annotations

from urllib.parse import urlencode

from ..config import get_settings
from ..models import LaunchStatus, TokenReport


def _stonfi_url(jetton: str) -> str:
    s = get_settings()
    params = {"ft": "TON", "tt": jetton}
    if s.stonfi_referral_address:
        params["referral_address"] = s.stonfi_referral_address
        params["referral_percent"] = s.stonfi_referral_percent
    return "https://app.ston.fi/swap?" + urlencode(params)


def _swapcoffee_url(jetton: str) -> str:
    s = get_settings()
    params = {"ft": "TON", "tt": jetton}
    if s.swapcoffee_referral_name:
        params["referral_name"] = s.swapcoffee_referral_name
    return "https://swap.coffee/dex?" + urlencode(params)


def _launchpad_url(launchpad: str | None, jetton: str) -> str | None:
    if not launchpad:
        return None
    low = launchpad.lower()
    if "gaspump" in low:
        return f"https://gaspump.tg/token/{jetton}"
    if "blum" in low:
        return f"https://t.me/blum/app?startapp=memepadjetton_{jetton}"
    return None


def _wrap_tracked(url: str, token: str, venue: str) -> str:
    """Route through hypha.link/b for click attribution; raw URL is the fallback."""
    s = get_settings()
    if not s.redirect_base:
        return url
    q = urlencode({"u": url, "t": token, "v": venue})
    return f"{s.redirect_base.rstrip('/')}/b?{q}"


def build_buy(report: TokenReport) -> dict | None:
    """Return {label, url, venue} for the Buy button, or None if not buyable yet."""
    info, lp, dex = report.token, report.launchpad, report.dex
    jetton = info.address

    # Still on a bonding curve -> send to the launchpad.
    if lp and lp.status == LaunchStatus.ON_CURVE:
        url = _launchpad_url(lp.launchpad, jetton)
        if url:
            venue = lp.launchpad or "launchpad"
            return {"label": f"🛒 Buy on {lp.launchpad}", "url": _wrap_tracked(url, jetton, venue), "venue": venue}

    if not dex or not dex.has_pool:
        return None

    # STON.fi referral is the strongest direct link when a STON.fi pool exists.
    if "stonfi" in (dex.venues or []) and get_settings().stonfi_referral_address:
        return {"label": "🛒 Buy", "url": _wrap_tracked(_stonfi_url(jetton), jetton, "stonfi"), "venue": "stonfi"}

    # Otherwise aggregate for best price via swap.coffee.
    return {"label": "🛒 Buy", "url": _wrap_tracked(_swapcoffee_url(jetton), jetton, "swapcoffee"), "venue": "swapcoffee"}
