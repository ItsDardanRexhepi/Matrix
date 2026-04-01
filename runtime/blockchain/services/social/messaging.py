"""XMTP Messaging - Component 28.

Wallet-to-wallet encrypted messaging using the XMTP protocol.
Messages are end-to-end encrypted and tied to wallet addresses.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class XMTPMessaging:
    """Wallet-to-wallet encrypted messaging via XMTP protocol.

    Provides end-to-end encrypted conversations between wallet addresses.
    In production, integrates with the XMTP network; this implementation
    provides the full message lifecycle with simulated encryption.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._conversations: dict[str, dict] = {}
        self._messages: dict[str, list[dict]] = {}  # conversation_id -> messages
        self._user_conversations: dict[str, list[str]] = {}  # address -> conversation_ids
        logger.info("XMTPMessaging initialised")

    def _conversation_key(self, addr1: str, addr2: str) -> str:
        """Deterministic conversation key for a pair of addresses."""
        pair = tuple(sorted([addr1, addr2]))
        return hashlib.sha256(f"{pair[0]}:{pair[1]}".encode()).hexdigest()[:24]

    def _encrypt_content(self, content: str, conversation_id: str) -> dict:
        """Simulate XMTP encryption. In production, uses XMTP SDK."""
        nonce = secrets.token_hex(12)
        # Simulated encryption: in production this uses X25519 + AES-256-GCM
        encrypted = hashlib.sha256(f"{content}:{nonce}:{conversation_id}".encode()).hexdigest()
        return {
            "ciphertext": encrypted,
            "nonce": nonce,
            "algorithm": "X25519-XMTP-AES256GCM",
            "original_length": len(content),
            # Store plaintext for retrieval in this implementation
            "_plaintext": content,
        }

    def _get_or_create_conversation(self, sender: str, recipient: str) -> dict:
        """Get or create a conversation between two addresses."""
        conv_key = self._conversation_key(sender, recipient)

        if conv_key not in self._conversations:
            conv_id = f"conv_{conv_key}"
            self._conversations[conv_key] = {
                "conversation_id": conv_id,
                "participants": sorted([sender, recipient]),
                "created_at": time.time(),
                "last_message_at": None,
                "message_count": 0,
            }
            self._messages[conv_id] = []

            # Link conversation to both users
            self._user_conversations.setdefault(sender, []).append(conv_id)
            self._user_conversations.setdefault(recipient, []).append(conv_id)

        return self._conversations[conv_key]

    async def send_message(self, sender: str, recipient: str, content: str, encrypted: bool = True) -> dict:
        """Send a message from one wallet to another.

        Args:
            sender: Sender's wallet address.
            recipient: Recipient's wallet address.
            content: Message content.
            encrypted: Whether to encrypt (default True).

        Returns:
            The message record.
        """
        if not sender:
            raise ValueError("sender is required")
        if not recipient:
            raise ValueError("recipient is required")
        if not content:
            raise ValueError("content is required")
        if sender == recipient:
            raise ValueError("Cannot send a message to yourself")

        conversation = self._get_or_create_conversation(sender, recipient)
        conv_id = conversation["conversation_id"]

        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        now = time.time()

        if encrypted:
            payload = self._encrypt_content(content, conv_id)
        else:
            payload = {"plaintext": content, "algorithm": "none"}

        message = {
            "message_id": message_id,
            "conversation_id": conv_id,
            "sender": sender,
            "recipient": recipient,
            "content": content if not encrypted else "[encrypted]",
            "payload": payload,
            "encrypted": encrypted,
            "timestamp": now,
            "read": False,
        }

        self._messages[conv_id].append(message)
        conversation["last_message_at"] = now
        conversation["message_count"] += 1

        logger.info(
            "Message %s sent from %s to %s (encrypted=%s, conv=%s)",
            message_id, sender, recipient, encrypted, conv_id,
        )

        # Return without internal plaintext
        result = {k: v for k, v in message.items()}
        if encrypted:
            result["payload"] = {k: v for k, v in payload.items() if not k.startswith("_")}
        return result

    async def get_conversations(self, address: str) -> list:
        """Get all conversations for an address.

        Args:
            address: Wallet address.

        Returns:
            List of conversation records.
        """
        if not address:
            raise ValueError("address is required")

        conv_ids = self._user_conversations.get(address, [])
        conversations = []
        for conv_id in conv_ids:
            # Find the conversation by scanning (conv_id is derived from conv_key)
            for conv in self._conversations.values():
                if conv["conversation_id"] == conv_id:
                    # Get the other participant
                    other = [p for p in conv["participants"] if p != address]
                    conversations.append({
                        **conv,
                        "other_participant": other[0] if other else None,
                    })
                    break

        conversations.sort(key=lambda x: x.get("last_message_at") or 0, reverse=True)
        return conversations

    async def get_messages(self, conversation_id: str, limit: int = 50) -> list:
        """Get messages in a conversation.

        Args:
            conversation_id: The conversation to retrieve.
            limit: Maximum messages to return.

        Returns:
            List of messages, most recent first.
        """
        if not conversation_id:
            raise ValueError("conversation_id is required")

        messages = self._messages.get(conversation_id)
        if messages is None:
            raise ValueError(f"Conversation '{conversation_id}' not found")

        # Return most recent first, without internal fields
        result = []
        for msg in reversed(messages[-limit:]):
            cleaned = {k: v for k, v in msg.items()}
            if cleaned.get("encrypted") and "payload" in cleaned:
                cleaned["payload"] = {
                    k: v for k, v in cleaned["payload"].items() if not k.startswith("_")
                }
            result.append(cleaned)
        return result
