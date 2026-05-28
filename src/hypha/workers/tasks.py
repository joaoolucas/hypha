"""arq task wrappers. The bot enqueues these for heavy work; results land in the cache.

For MVP the main analysis runs inline in the bot; these exist so Phase 3/4 fan-out
(bundling graph, top-wallet portfolios) can move off the bot loop without refactoring.
"""

from __future__ import annotations

from ..analysis.service import analyze_token


async def analyze_task(ctx, address: str, force: bool = False) -> dict:
    report = await analyze_token(address, force=force)
    return report.model_dump()
