"""Whale-tracker — the push side of Hypha. Watches the hottest TON pools' trade feeds for big
buys/sells, enriches each with the Hypha read + trader context, and posts alerts to a channel.
Recurring big buyers get auto-promoted to a followed list and tracked into cold tokens too.
"""
