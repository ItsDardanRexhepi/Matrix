"""
Mythos Preview — Glasswing cybersecurity-focused frontier model.

Uses the Anthropic API but targets Mythos Preview specifically.
Glasswing models are optimised for vulnerability detection, code security
analysis, and exploit identification.

Access: Anthropic API, Amazon Bedrock, Google Vertex AI, Microsoft Foundry.
"""

from __future__ import annotations

import logging

from runtime.models.anthropic_client import AnthropicClient

logger = logging.getLogger(__name__)

DEFAULT_MYTHOS_MODEL = "claude-opus-4-6"


class MythosClient(AnthropicClient):
    """Anthropic Mythos model provider — security-optimised frontier model.

    Inherits all Anthropic API logic. Overrides the model name to target
    Mythos Preview for security-critical operations.
    """

    def __init__(self, config: dict) -> None:
        config = dict(config)
        config.setdefault("model", DEFAULT_MYTHOS_MODEL)
        super().__init__(config)
        logger.info("Mythos client initialised: model=%s", self.model)
