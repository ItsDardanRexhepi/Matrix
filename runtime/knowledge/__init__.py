"""Real-time knowledge injection for 0pnMatrx agents.

Fetches live blockchain data, market prices, and platform activity
to enrich agent context.  Every external call has a strict timeout
and fails silently — a knowledge fetch must never delay or break
a response.
"""

from runtime.knowledge.retriever import KnowledgeRetriever

__all__ = ["KnowledgeRetriever"]
