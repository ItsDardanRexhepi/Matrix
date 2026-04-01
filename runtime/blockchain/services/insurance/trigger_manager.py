"""
TriggerManager — monitors oracle data for automatic parametric triggers.

Evaluates registered conditions against real-time oracle data (via the
OracleGateway, Component 11) and auto-initiates claims when conditions
are met.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class TriggerManager:
    """Manages parametric triggers for insurance policies.

    Config keys (under ``config["insurance"]``):
        trigger_check_interval: seconds between checks (default 300).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        ins_cfg = config.get("insurance", {})
        self._check_interval: int = int(
            ins_cfg.get("trigger_check_interval", 300)
        )

        # trigger_id -> trigger record
        self._triggers: dict[str, dict[str, Any]] = {}

    async def register_trigger(
        self,
        policy_id: str,
        trigger_type: str,
        conditions: dict,
    ) -> dict:
        """Register a new trigger for a policy.

        Args:
            policy_id: The associated policy.
            trigger_type: Same as policy_type (weather, earthquake, etc.).
            conditions: Type-specific conditions with thresholds.

        Returns:
            Trigger record with ``trigger_id``.
        """
        trigger_id = f"trg_{uuid.uuid4().hex[:16]}"
        trigger: dict[str, Any] = {
            "trigger_id": trigger_id,
            "policy_id": policy_id,
            "trigger_type": trigger_type,
            "conditions": conditions,
            "status": "active",
            "created_at": int(time.time()),
            "last_checked": 0,
            "triggered": False,
        }
        self._triggers[trigger_id] = trigger

        logger.info(
            "Trigger registered: id=%s policy=%s type=%s",
            trigger_id, policy_id, trigger_type,
        )
        return trigger

    async def deregister_trigger(self, trigger_id: str) -> dict:
        """Deactivate a trigger."""
        trigger = self._triggers.get(trigger_id)
        if not trigger:
            return {"status": "not_found", "trigger_id": trigger_id}
        trigger["status"] = "deactivated"
        return {"status": "deactivated", "trigger_id": trigger_id}

    async def check_triggers(self) -> list:
        """Check all active triggers against oracle data.

        Returns a list of triggers whose conditions were met.
        """
        triggered: list[dict[str, Any]] = []
        now = int(time.time())

        active = [
            t for t in self._triggers.values()
            if t["status"] == "active" and not t["triggered"]
        ]

        for trigger in active:
            # Respect check interval
            if now - trigger["last_checked"] < self._check_interval:
                continue

            trigger["last_checked"] = now

            try:
                oracle_data = await self._fetch_oracle_data(trigger)
                met = await self.evaluate_condition(trigger, oracle_data)

                if met:
                    trigger["triggered"] = True
                    trigger["status"] = "triggered"
                    trigger["triggered_at"] = now
                    trigger["oracle_data"] = oracle_data
                    triggered.append(trigger)
                    logger.info(
                        "Trigger fired: id=%s policy=%s",
                        trigger["trigger_id"], trigger["policy_id"],
                    )
            except Exception as exc:
                logger.warning(
                    "Trigger check failed for %s: %s",
                    trigger["trigger_id"], exc,
                )

        return triggered

    async def evaluate_condition(
        self,
        trigger: dict,
        oracle_data: dict | None = None,
    ) -> bool:
        """Evaluate whether a trigger's conditions are met.

        Args:
            trigger: The trigger record.
            oracle_data: Pre-fetched oracle data, or None to fetch fresh.

        Returns:
            True if the condition is met.
        """
        if oracle_data is None:
            oracle_data = await self._fetch_oracle_data(trigger)

        conditions = trigger.get("conditions", {})
        trigger_type = trigger.get("trigger_type", "")

        if trigger_type == "weather":
            return self._eval_weather(conditions, oracle_data)
        elif trigger_type == "flight_delay":
            return self._eval_flight_delay(conditions, oracle_data)
        elif trigger_type == "crop":
            return self._eval_crop(conditions, oracle_data)
        elif trigger_type == "earthquake":
            return self._eval_earthquake(conditions, oracle_data)
        elif trigger_type == "smart_contract_hack":
            return self._eval_hack(conditions, oracle_data)

        return False

    # ------------------------------------------------------------------
    # Condition evaluators
    # ------------------------------------------------------------------

    @staticmethod
    def _eval_weather(conditions: dict, data: dict) -> bool:
        metric = conditions.get("metric", "temperature")
        threshold = float(conditions.get("threshold", 0))
        comparator = conditions.get("comparator", "gt")
        value = data.get(metric)

        if value is None:
            return False
        value = float(value)

        if comparator == "gt":
            return value > threshold
        elif comparator == "lt":
            return value < threshold
        elif comparator == "gte":
            return value >= threshold
        elif comparator == "lte":
            return value <= threshold
        elif comparator == "eq":
            return value == threshold
        return False

    @staticmethod
    def _eval_flight_delay(conditions: dict, data: dict) -> bool:
        delay_threshold = int(conditions.get("delay_minutes", 120))
        actual_delay = int(data.get("delay_minutes", 0))
        return actual_delay >= delay_threshold

    @staticmethod
    def _eval_crop(conditions: dict, data: dict) -> bool:
        threshold = float(conditions.get("rainfall_threshold_mm", 50))
        actual = float(data.get("rainfall_mm", 999))
        # Trigger if rainfall is BELOW threshold (drought)
        return actual < threshold

    @staticmethod
    def _eval_earthquake(conditions: dict, data: dict) -> bool:
        threshold = float(conditions.get("magnitude_threshold", 5.0))
        magnitude = float(data.get("magnitude", 0))
        return magnitude >= threshold

    @staticmethod
    def _eval_hack(conditions: dict, data: dict) -> bool:
        loss_threshold = float(conditions.get("loss_threshold", 0))
        reported_loss = float(data.get("loss_amount", 0))
        is_hacked = data.get("hack_detected", False)
        return bool(is_hacked) and reported_loss >= loss_threshold

    # ------------------------------------------------------------------
    # Oracle integration
    # ------------------------------------------------------------------

    async def _fetch_oracle_data(self, trigger: dict) -> dict[str, Any]:
        """Fetch relevant oracle data for a trigger via OracleGateway.

        Attempts to use the OracleGateway (Component 11) if available;
        falls back to returning empty data so the caller can handle it.
        """
        trigger_type = trigger.get("trigger_type", "")
        conditions = trigger.get("conditions", {})

        try:
            from runtime.blockchain.services.oracle_gateway import OracleGateway

            gw = OracleGateway(self._config)

            if trigger_type == "weather":
                return await gw.request(
                    "weather",
                    {"location": conditions.get("location", "")},
                    caller="insurance_trigger",
                )
            elif trigger_type == "earthquake":
                return await gw.request(
                    "custom",
                    {
                        "url": self._config.get("insurance", {}).get(
                            "earthquake_api",
                            "https://earthquake.usgs.gov/fdsnws/event/1/query",
                        ),
                        "method": "GET",
                    },
                    caller="insurance_trigger",
                )
            elif trigger_type in ("flight_delay", "crop", "smart_contract_hack"):
                return await gw.request(
                    "custom",
                    {
                        "url": self._config.get("insurance", {}).get(
                            f"{trigger_type}_api", ""
                        ),
                        "method": "GET",
                    },
                    caller="insurance_trigger",
                )
        except ImportError:
            logger.debug("OracleGateway not available, returning empty data.")
        except Exception as exc:
            logger.warning("Oracle fetch failed for trigger %s: %s",
                           trigger["trigger_id"], exc)

        return {}
