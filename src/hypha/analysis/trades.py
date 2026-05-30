"""Swap classification — the heart of "tal whale comprou tal memecoin".

Two sources feed the same normalized `Trade`:
  • GeckoTerminal pool trades  → token-centric loop (any big buyer on a hot pool)
  • TonAPI account events       → wallet-centric loop (a followed whale, even on cold tokens)

Both are pure transforms (no I/O) so they're unit-tested against fixtures. USD sizing on the
Gecko path comes straight from the feed; the TonAPI path leaves `usd` 0 to be priced at enrich
time (events carry amounts, not USD).
"""

from __future__ import annotations

from datetime import datetime

from ..models import HotPool, Trade, TradeSide
from ..utils import to_raw
from .discovery import is_stable


def _f(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _parse_ts(s) -> float:
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def parse_gecko_trades(
    raw_trades: list[dict],
    pool: HotPool,
    *,
    buy_min: float,
    sell_min: float,
) -> list[Trade]:
    """Classify a pool's recent swaps as buy/sell of the pool's memecoin and apply the
    side-specific USD floors. Direction is read from the from/to token addresses (robust to
    base/quote ordering), falling back to the feed's `kind` flag."""
    token_raw = to_raw(pool.token_address)
    out: list[Trade] = []
    for t in raw_trades:
        a = t.get("attributes") or {}
        from_addr = to_raw(a.get("from_token_address", ""))
        to_addr = to_raw(a.get("to_token_address", ""))

        if to_addr and to_addr == token_raw:
            side = TradeSide.BUY
        elif from_addr and from_addr == token_raw:
            side = TradeSide.SELL
        else:                                          # fall back to kind + base/quote layout
            kind = (a.get("kind") or "").lower()
            if kind not in ("buy", "sell"):
                continue
            bought_base = kind == "buy"
            side = TradeSide.BUY if bought_base == pool.token_is_base else TradeSide.SELL

        usd = _f(a.get("volume_in_usd"))
        if side == TradeSide.BUY and usd < buy_min:
            continue
        if side == TradeSide.SELL and usd < sell_min:
            continue

        amount = _f(a.get("to_token_amount") if side == TradeSide.BUY else a.get("from_token_amount"))
        price = _f(a.get("price_to_in_usd") if side == TradeSide.BUY else a.get("price_from_in_usd"))
        out.append(Trade(
            side=side,
            token_address=pool.token_address,
            token_symbol=pool.token_symbol,
            trader=to_raw(a.get("tx_from_address", "")),
            usd=round(usd, 2),
            token_amount=amount,
            price_usd=price or None,
            venue=pool.venue,
            pool_address=pool.pool_address,
            tx_hash=a.get("tx_hash", ""),
            ts=_parse_ts(a.get("block_timestamp")),
            source="gecko",
        ))
    return out


def _master(side_obj: dict | None) -> dict:
    return side_obj or {}


def parse_tonapi_events(events: list[dict], wallet_raw: str) -> list[Trade]:
    """Pull jetton buys/sells out of a followed wallet's TonAPI events. USD is left 0 (events
    don't carry it) — the enricher prices it from the token's market data. Only TON-paired and
    stable-paired swaps are classified; pure jetton↔jetton swaps are skipped as ambiguous."""
    out: list[Trade] = []
    for ev in events:
        ts = float(ev.get("timestamp", 0) or 0)
        event_id = ev.get("event_id", "")
        for act in ev.get("actions", []) or []:
            if act.get("type") != "JettonSwap" or act.get("status") == "failed":
                continue
            sw = act.get("JettonSwap") or {}
            jm_in, jm_out = _master(sw.get("jetton_master_in")), _master(sw.get("jetton_master_out"))
            ton_in = _f(sw.get("ton_in"))
            ton_out = _f(sw.get("ton_out"))

            paid_money = ton_in > 0 or is_stable(jm_in.get("symbol", ""))
            got_money = ton_out > 0 or is_stable(jm_out.get("symbol", ""))

            if jm_out.get("address") and paid_money:          # spent money, received a jetton
                side, master, amount_units = TradeSide.BUY, jm_out, sw.get("amount_out")
            elif jm_in.get("address") and got_money:           # gave up a jetton, received money
                side, master, amount_units = TradeSide.SELL, jm_in, sw.get("amount_in")
            else:
                continue

            try:
                decimals = int(master.get("decimals", 9) or 9)
            except (TypeError, ValueError):
                decimals = 9
            out.append(Trade(
                side=side,
                token_address=master.get("address", ""),
                token_symbol=master.get("symbol", ""),
                trader=wallet_raw,
                usd=0.0,                                       # priced at enrich time
                token_amount=_f(amount_units) / (10 ** decimals),
                venue=sw.get("dex", ""),
                tx_hash=event_id,
                ts=ts,
                source="tonapi",
            ))
    return out
