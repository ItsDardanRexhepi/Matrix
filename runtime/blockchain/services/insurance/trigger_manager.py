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

from ._oracle_contract import (
    Verdict,
    extract_measurement,
    read_measurement,
    read_number,
)

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

    def get_trigger(self, trigger_id: str) -> dict | None:
        """Look up a registered trigger. NEW-78 — lets the claim path reach
        the ORACLE verifier instead of trusting caller-supplied data."""
        return self._triggers.get(trigger_id)

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
            True if the condition is met. FALSE COLLAPSES TWO DIFFERENT FACTS —
            "the event did not happen" and "we could not measure it" — so any
            caller that reports a decision to a claimant must use
            :meth:`evaluate_condition_detailed` instead. Kept boolean because
            its own callers only need the fail-closed answer (§AK: this
            returns the callee's verdict, and the callee is the honest one).
        """
        return (await self.evaluate_condition_detailed(trigger, oracle_data)).met

    async def evaluate_condition_detailed(
        self,
        trigger: dict,
        oracle_data: dict | None = None,
    ) -> Verdict:
        """Evaluate a trigger, distinguishing "not met" from "not measured".

        DOMAIN 18-D. The measurement is located through the oracle contract
        (:mod:`._oracle_contract`) rather than read off whatever dict arrives,
        because WHERE IT LIVES DEPENDS ON THE ORACLE TYPE: weather responses
        are merged flat into the gateway envelope, while every custom-backed
        type nests the provider body under ``"data"``. Reading the top level
        was correct for neither, and each evaluator silently substituted an
        insurer-favourable default for the field it failed to find.

        Accepts either a raw gateway envelope or an already-extracted
        measurement, so both call paths — the pre-fetched one in
        ``check_triggers`` and the fresh one here — go through the same door.
        """
        if oracle_data is None:
            oracle_data = await self._fetch_oracle_data(trigger)

        conditions = trigger.get("conditions", {})
        trigger_type = trigger.get("trigger_type", "")

        measurement = extract_measurement(oracle_data)
        if measurement is None:
            return Verdict(
                met=False,
                measured=False,
                reason=(
                    "the oracle returned no measurement, so the covered event "
                    "could not be checked."
                ),
            )

        evaluator = {
            "weather": self._eval_weather,
            "flight_delay": self._eval_flight_delay,
            "crop": self._eval_crop,
            "earthquake": self._eval_earthquake,
            "smart_contract_hack": self._eval_hack,
        }.get(trigger_type)

        if evaluator is None:
            return Verdict(
                met=False,
                measured=False,
                reason=(
                    f"no evaluator is registered for trigger type "
                    f"'{trigger_type}', so the covered event could not be "
                    f"checked."
                ),
            )

        return evaluator(conditions, measurement)

    # ------------------------------------------------------------------
    # Condition evaluators
    # ------------------------------------------------------------------

    @staticmethod
    def _unmeasured(field: str) -> Verdict:
        """The oracle answered, but not about the thing the policy insures."""
        return Verdict(
            met=False,
            measured=False,
            reason=(
                f"the oracle response did not report '{field}', so the covered "
                f"event could not be checked."
            ),
        )

    @staticmethod
    def _eval_weather(conditions: dict, data: dict) -> Verdict:
        metric = conditions.get("metric", "temperature")
        threshold = float(conditions.get("threshold", 0))
        comparator = conditions.get("comparator", "gt")

        value = read_number(data, metric)
        if value is None:
            return TriggerManager._unmeasured(metric)

        outcomes = {
            "gt": value > threshold,
            "lt": value < threshold,
            "gte": value >= threshold,
            "lte": value <= threshold,
            "eq": value == threshold,
        }
        if comparator not in outcomes:
            return Verdict(
                met=False,
                measured=False,
                reason=(
                    f"the comparator '{comparator}' is not recognised, so the "
                    f"policy trigger could not be evaluated."
                ),
            )
        return Verdict(
            met=outcomes[comparator],
            measured=True,
            reason=f"Measured {metric}={value}, threshold {comparator} {threshold}.",
        )

    @staticmethod
    def _eval_flight_delay(conditions: dict, data: dict) -> Verdict:
        delay_threshold = int(conditions.get("delay_minutes", 120))
        actual_delay = read_number(data, "delay_minutes")
        if actual_delay is None:
            return TriggerManager._unmeasured("delay_minutes")
        return Verdict(
            met=actual_delay >= delay_threshold,
            measured=True,
            reason=(
                f"Measured delay {actual_delay} minutes against a "
                f"{delay_threshold}-minute threshold."
            ),
        )

    @staticmethod
    def _eval_crop(conditions: dict, data: dict) -> Verdict:
        threshold = float(conditions.get("rainfall_threshold_mm", 50))
        actual = read_number(data, "rainfall_mm")
        if actual is None:
            # Pre-fix this defaulted to 999mm — a fabricated downpour that
            # denied every drought claim the policy existed to pay.
            return TriggerManager._unmeasured("rainfall_mm")
        # Trigger if rainfall is BELOW threshold (drought)
        return Verdict(
            met=actual < threshold,
            measured=True,
            reason=(
                f"Measured rainfall {actual}mm against a {threshold}mm drought "
                f"threshold."
            ),
        )

    @staticmethod
    def _eval_earthquake(conditions: dict, data: dict) -> Verdict:
        threshold = float(conditions.get("magnitude_threshold", 5.0))
        magnitude = read_number(data, "magnitude")
        if magnitude is None:
            return TriggerManager._unmeasured("magnitude")
        return Verdict(
            met=magnitude >= threshold,
            measured=True,
            reason=(
                f"Measured magnitude {magnitude} against a {threshold} "
                f"threshold."
            ),
        )

    @staticmethod
    def _eval_hack(conditions: dict, data: dict) -> Verdict:
        loss_threshold = float(conditions.get("loss_threshold", 0))
        reported_loss = read_number(data, "loss_amount")
        is_hacked = read_measurement(data, "hack_detected")

        # BOTH fields are decision inputs, so BOTH must be present. Pre-fix
        # `hack_detected` defaulted to False, which denied every claim, while
        # `loss_amount` defaulted to 0.0, which — with the shipped default
        # threshold of 0 — satisfied the comparison. The two defaults pointed
        # in opposite directions on the same reading.
        if is_hacked is None:
            return TriggerManager._unmeasured("hack_detected")
        if reported_loss is None:
            return TriggerManager._unmeasured("loss_amount")

        return Verdict(
            met=bool(is_hacked) and reported_loss >= loss_threshold,
            measured=True,
            reason=(
                f"Measured hack_detected={bool(is_hacked)}, loss "
                f"{reported_loss} against a {loss_threshold} threshold."
            ),
        )

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
