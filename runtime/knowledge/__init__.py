"""Real-time knowledge injection for The Matrix agents.

Fetches live blockchain data, market prices, and platform activity
to enrich agent context.  Every external call has a strict timeout
and fails silently — a knowledge fetch must never delay or break
a response.

"Never delay" is a claim about the caller's path, and it is kept the only way
it can be: nothing is awaited there. ``get_relevant_context`` reads a
process-wide cache and returns; a missing or expired entry schedules a
background refresh for the next turn. The first turn after a cold start
carries no live data, which is the price of the sentence and cheaper than the
two and a half seconds it used to cost. See :mod:`runtime.knowledge.retriever`.
"""

from runtime.knowledge.retriever import KnowledgeRetriever, clear_cache

__all__ = ["KnowledgeRetriever", "clear_cache"]
