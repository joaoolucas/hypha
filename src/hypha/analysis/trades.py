"""Swap classification — the heart of "this whale bought this memecoin".

All three feeds produce the same normalized `Trade`:
  • TonAPI pool events    → token-centric loop (any big buyer on a hot pool)   [primary]
  • TonAPI account events → wallet-centric loop (a followed whale, cold tokens too)
  • GeckoTerminal trades  → legacy/alt path, kept for completeness

We read trades from TonAPI (reliable, paid tier) rather than GeckoTerminal's free tier, which
hard-throttles server-side polling. Gecko is used only for hot-pool discovery now. All parsers
are pure transforms (no I/O) so they're unit-tested. TonAPI events carry no USD, so swaps are
sized by their TON leg (TON amount × TON/USD), with token-price as a later fallback.
"""

from __future__ import annotations

from datetime import datetime

from pytoniq_core import Cell

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


_NANOTON = 10 ** 9


def parse_pool_events(events: list[dict], pool, ton_usd: float = 0.0) -> list[Trade]:
    """Token-centric feed: pull buys/sells of a pool's memecoin out of the pool's TonAPI events.
    The trader is each swap's own `user_wallet` (not the queried account). Direction is read from
    which side of the swap carries the pool's token. Sized by the TON leg (× ton_usd); jetton/jetton
    or pTON-paired swaps leave usd 0 to be priced from the token's market data later."""
    token_raw = to_raw(pool.token_address)
    out: list[Trade] = []
    for ev in events:
        ts = float(ev.get("timestamp", 0) or 0)
        event_id = ev.get("event_id", "")
        for act in ev.get("actions", []) or []:
            if act.get("type") != "JettonSwap" or act.get("status") == "failed":
                continue
            sw = act.get("JettonSwap") or {}
            jm_in, jm_out = sw.get("jetton_master_in") or {}, sw.get("jetton_master_out") or {}

            if to_raw(jm_out.get("address", "")) == token_raw:
                side, master, amount_units, ton_leg = (
                    TradeSide.BUY, jm_out, sw.get("amount_out"), _f(sw.get("ton_in")))
            elif to_raw(jm_in.get("address", "")) == token_raw:
                side, master, amount_units, ton_leg = (
                    TradeSide.SELL, jm_in, sw.get("amount_in"), _f(sw.get("ton_out")))
            else:
                continue                              # swap doesn't involve this pool's token

            try:
                decimals = int(master.get("decimals", 9) or 9)
            except (TypeError, ValueError):
                decimals = 9
            ton_value = ton_leg / _NANOTON
            usd = round(ton_value * ton_usd, 2) if (ton_leg and ton_usd) else 0.0
            out.append(Trade(
                side=side,
                token_address=pool.token_address,
                token_symbol=pool.token_symbol or master.get("symbol", ""),
                trader=to_raw((sw.get("user_wallet") or {}).get("address", "")),
                usd=usd,
                ton_value=round(ton_value, 2),
                token_amount=_f(amount_units) / (10 ** decimals),
                venue=sw.get("dex", "") or pool.venue,
                pool_address=pool.pool_address,
                tx_hash=event_id,
                ts=ts,
                source="tonapi",
            ))
    return out


_URANUS_BUY = 0xA0AA6BC2     # Topblast/Uranus BuyEvent  (amountIn=TON, amountOut=tokens)
_URANUS_SELL = 0x3AB0FCCC    # Topblast/Uranus SellEvent (amountIn=tokens, amountOut=TON)


def parse_uranus_events(transactions: list[dict], pool: HotPool, ton_usd: float = 0.0) -> list[Trade]:
    """Decode Topblast/Uranus on-chain trade events. The Meme contract (the token's jetton master)
    emits a BuyEvent/SellEvent as an external out-message after each trade; we parse the body cell
    exactly per the documented layout (op, trader, amountIn, amountOut). No heuristics."""
    out: list[Trade] = []
    for tx in transactions:
        ts = float(tx.get("utime", 0) or 0)
        tx_hash = tx.get("hash", "")
        for m in tx.get("out_msgs", []) or []:
            if m.get("op_code") not in ("0xa0aa6bc2", "0x3ab0fccc") or not m.get("raw_body"):
                continue
            try:
                s = Cell.one_from_boc(bytes.fromhex(m["raw_body"])).begin_parse()
                op = s.load_uint(32)
                trader = s.load_address()
                amount_in = s.load_coins()
                amount_out = s.load_coins()
            except Exception:  # noqa: BLE001 — skip a malformed event body
                continue
            if trader is None:
                continue
            if op == _URANUS_BUY:
                side, ton_nano, token_nano = TradeSide.BUY, amount_in, amount_out
            else:
                side, ton_nano, token_nano = TradeSide.SELL, amount_out, amount_in
            ton_value = (ton_nano or 0) / 1e9
            out.append(Trade(
                side=side,
                token_address=pool.token_address,
                token_symbol=pool.token_symbol,
                trader=f"{trader.wc}:{trader.hash_part.hex()}",
                usd=round(ton_value * ton_usd, 2) if ton_usd else 0.0,
                ton_value=round(ton_value, 2),
                token_amount=(token_nano or 0) / 1e9,
                venue=pool.venue or "uranus",
                pool_address=pool.pool_address,
                tx_hash=tx_hash,
                ts=ts,
                source="uranus",
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
            ton_leg = ton_in if side == TradeSide.BUY else ton_out
            out.append(Trade(
                side=side,
                token_address=master.get("address", ""),
                token_symbol=master.get("symbol", ""),
                trader=wallet_raw,
                usd=0.0,                                       # priced at enrich time
                ton_value=round(ton_leg / _NANOTON, 2),
                token_amount=_f(amount_units) / (10 ** decimals),
                venue=sw.get("dex", ""),
                tx_hash=event_id,
                ts=ts,
                source="tonapi",
            ))
    return out
