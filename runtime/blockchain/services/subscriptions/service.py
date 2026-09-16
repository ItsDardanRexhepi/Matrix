"""Subscription & Recurring Rewards Service - Component 27.

Manages subscription plans, user subscriptions, renewals, and rewards.
10% of subscription revenue goes to the platform. 48-hour grace period
for failed payments.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from .rewards import RecurringRewards
from runtime.protocols.outcome_truth import FAILURE, SUCCESS, report_of

from .grace_period import GracePeriodManager

logger = logging.getLogger(__name__)

VALID_INTERVALS = {"daily", "weekly", "monthly", "quarterly", "yearly"}

INTERVAL_SECONDS: dict[str, int] = {
    "daily": 86400,
    "weekly": 604800,
    "monthly": 2592000,     # 30 days
    "quarterly": 7776000,   # 90 days
    "yearly": 31536000,     # 365 days
}

DEFAULT_CONFIG: dict[str, Any] = {
    "platform_fee_pct": 10.0,
    "platform_wallet": "0xPLATFORM_TREASURY",
    "grace_period_hours": 48,
    "max_retry_attempts": 3,
}


class SubscriptionService:
    """Subscription management with recurring rewards and grace periods.

    Providers create plans; users subscribe and receive recurring rewards.
    10% of subscription revenue goes to the platform.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self._plans: dict[str, dict] = {}
        self._subscriptions: dict[str, dict] = {}
        self.rewards = RecurringRewards(self.config)
        self.grace = GracePeriodManager(self.config)
        logger.info(
            "SubscriptionService initialised (platform_fee=%.0f%%, grace=%dh)",
            self.config["platform_fee_pct"],
            self.config["grace_period_hours"],
        )

    async def create_plan(self, provider: str, name: str, price: float, interval: str, rewards: dict) -> dict:
        """Create a subscription plan.

        Args:
            provider: Provider's wallet address.
            name: Plan name.
            price: Price per billing interval.
            interval: Billing interval ('daily', 'weekly', 'monthly', 'quarterly', 'yearly').
            rewards: Reward configuration for subscribers.

        Returns:
            The created plan record.
        """
        if not provider:
            raise ValueError("provider is required")
        if not name:
            raise ValueError("name is required")
        if price <= 0:
            raise ValueError("price must be positive")
        if interval not in VALID_INTERVALS:
            raise ValueError(f"Invalid interval '{interval}'. Must be one of: {VALID_INTERVALS}")

        plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        now = time.time()

        plan = {
            "plan_id": plan_id,
            "provider": provider,
            "name": name,
            "price": price,
            "interval": interval,
            "interval_seconds": INTERVAL_SECONDS[interval],
            "rewards": rewards,
            "platform_fee_pct": self.config["platform_fee_pct"],
            "status": "active",
            "subscriber_count": 0,
            "created_at": now,
            "updated_at": now,
        }

        self._plans[plan_id] = plan
        logger.info("Plan %s created by %s (name=%s, price=%.2f/%s)", plan_id, provider, name, price, interval)
        return plan

    async def subscribe(self, user: str, plan_id: str, payment_token: str) -> dict:
        """Subscribe a user to a plan.

        Args:
            user: User's wallet address.
            plan_id: Plan to subscribe to.
            payment_token: Payment authorization token.

        Returns:
            The subscription record.
        """
        if not user:
            raise ValueError("user is required")
        if not payment_token:
            raise ValueError("payment_token is required")

        plan = self._plans.get(plan_id)
        if not plan:
            raise ValueError(f"Plan '{plan_id}' not found")
        if plan["status"] != "active":
            raise ValueError(f"Plan '{plan_id}' is not active")

        # Check for existing active subscription to same plan
        for sub in self._subscriptions.values():
            if sub["user"] == user and sub["plan_id"] == plan_id and sub["status"] == "active":
                raise ValueError(f"User already has an active subscription to plan '{plan_id}'")

        subscription_id = f"sub_{uuid.uuid4().hex[:12]}"
        now = time.time()

        fee_pct = self.config["platform_fee_pct"] / 100.0
        platform_fee = round(plan["price"] * fee_pct, 8)
        provider_receives = round(plan["price"] - platform_fee, 8)

        subscription = {
            "subscription_id": subscription_id,
            "user": user,
            "plan_id": plan_id,
            "plan_name": plan["name"],
            "provider": plan["provider"],
            "price": plan["price"],
            "interval": plan["interval"],
            "payment_token": payment_token,
            "status": "active",
            "platform_fee": platform_fee,
            "provider_receives": provider_receives,
            "current_period_start": now,
            "current_period_end": now + plan["interval_seconds"],
            "next_renewal_at": now + plan["interval_seconds"],
            # NOT 1 and NOT plan["price"]. Nothing was charged: `payment_token`
            # is a string the subscriber supplies and no code in this service
            # presents it to anything. These are the counters a provider is paid
            # from and a user is shown; they count SETTLED charges.
            "billing_count": 0,
            "total_paid": 0.0,
            "charges_settled": False,
            "subscribed_at": now,
            "cancelled_at": None,
            "grace_entries": 0,
            "rewards_config": plan["rewards"],
        }

        self._subscriptions[subscription_id] = subscription
        plan["subscriber_count"] += 1

        # Initialize rewards
        await self.rewards.initialize_subscription(subscription_id, plan["rewards"])

        logger.info(
            "User %s subscribed to plan %s (sub_id=%s, price=%.2f/%s)",
            user, plan_id, subscription_id, plan["price"], plan["interval"],
        )
        return subscription

    async def cancel(self, subscription_id: str, user: str) -> dict:
        """Cancel a subscription.

        The subscription remains active until the current period ends.

        Args:
            subscription_id: Subscription to cancel.
            user: Must match the subscriber.

        Returns:
            The updated subscription record.
        """
        sub = self._subscriptions.get(subscription_id)
        if not sub:
            raise ValueError(f"Subscription '{subscription_id}' not found")
        if sub["user"] != user:
            raise ValueError("Only the subscriber can cancel")
        if sub["status"] not in ("active", "grace_period"):
            raise ValueError(f"Cannot cancel subscription with status '{sub['status']}'")

        sub["status"] = "cancelled"
        sub["cancelled_at"] = time.time()

        plan = self._plans.get(sub["plan_id"])
        if plan:
            plan["subscriber_count"] = max(0, plan["subscriber_count"] - 1)

        logger.info("Subscription %s cancelled by user %s", subscription_id, user)
        return sub

    async def get_subscription(self, subscription_id: str) -> dict:
        """Get a subscription by ID."""
        sub = self._subscriptions.get(subscription_id)
        if not sub:
            raise ValueError(f"Subscription '{subscription_id}' not found")
        return sub

    async def process_renewals(self) -> list:
        """Batch process all due renewals.

        Attempts payment for subscriptions whose current period has ended.
        Failed payments enter a 48-hour grace period.

        Returns:
            List of renewal results.
        """
        now = time.time()
        results = []

        for sub_id, sub in self._subscriptions.items():
            if sub["status"] != "active":
                continue
            if now < sub["next_renewal_at"]:
                continue

            # Attempt renewal
            renewal_result = await self._process_single_renewal(sub_id, sub, now)
            results.append(renewal_result)

        # Also check grace period expirations
        for sub_id, sub in self._subscriptions.items():
            if sub["status"] == "grace_period":
                grace_check = await self.grace.check_grace(sub_id)
                if grace_check.get("expired"):
                    sub["status"] = "cancelled"
                    sub["cancelled_at"] = now
                    plan = self._plans.get(sub["plan_id"])
                    if plan:
                        plan["subscriber_count"] = max(0, plan["subscriber_count"] - 1)
                    results.append({
                        "subscription_id": sub_id,
                        "action": "auto_cancelled",
                        "reason": "grace_period_expired",
                    })
                    logger.info("Subscription %s auto-cancelled: grace period expired", sub_id)

        logger.info("Processed renewals: %d results", len(results))
        return results

    async def _process_single_renewal(self, sub_id: str, sub: dict, now: float) -> dict:
        """Process renewal for a single subscription."""
        plan = self._plans.get(sub["plan_id"])
        if not plan:
            sub["status"] = "cancelled"
            return {"subscription_id": sub_id, "action": "cancelled", "reason": "plan_not_found"}

        payment = await self._attempt_payment(sub)
        outcome = payment.get("status")

        if outcome not in ("paid", "declined"):
            # THE THIRD ANSWER. The charge neither settled nor was refused, so
            # the counters do not move, the period does not roll forward and the
            # subscription is NOT pushed toward cancellation. The renewal stays
            # due, which is what it is: when a gateway appears, it is charged.
            sub["renewal_blocked_since"] = sub.get("renewal_blocked_since") or now
            logger.warning(
                "Subscription %s renewal not charged: %s",
                sub_id, payment.get("reason") or payment.get("status"),
            )
            return {
                "subscription_id": sub_id,
                "action": "not_charged",
                "status": "recorded_unsettled",
                "settled": False,
                "value_moved": False,
                "reason": payment.get("reason") or payment.get("status"),
                "payment": payment,
                "disclosure": (
                    "No charge was attempted or none could be confirmed. The "
                    "billing counters were NOT advanced and the subscription "
                    "was NOT moved toward cancellation — the renewal is still "
                    "due."
                ),
            }

        if outcome == "paid":
            sub.pop("renewal_blocked_since", None)
            fee_pct = self.config["platform_fee_pct"] / 100.0
            platform_fee = round(plan["price"] * fee_pct, 8)

            sub["billing_count"] += 1
            sub["total_paid"] = round(sub["total_paid"] + plan["price"], 8)
            sub["charges_settled"] = True
            sub["current_period_start"] = now
            sub["current_period_end"] = now + plan["interval_seconds"]
            sub["next_renewal_at"] = now + plan["interval_seconds"]

            # Distribute rewards for the new period
            await self.rewards.distribute_rewards(sub_id)

            logger.info("Subscription %s renewed (billing #%d)", sub_id, sub["billing_count"])
            return {
                "subscription_id": sub_id,
                "action": "renewed",
                "billing_count": sub["billing_count"],
                "platform_fee": platform_fee,
                "next_renewal_at": sub["next_renewal_at"],
            }
        else:
            # Enter grace period
            await self.grace.enter_grace(sub_id)
            sub["status"] = "grace_period"
            sub["grace_entries"] += 1

            logger.warning("Subscription %s payment failed, entering grace period", sub_id)
            return {
                "subscription_id": sub_id,
                "action": "grace_period",
                "reason": "payment_failed",
                "grace_expires_at": now + self.config["grace_period_hours"] * 3600,
            }

    async def _attempt_payment(self, sub: dict) -> dict:
        """Attempt payment for a subscription renewal, and say what happened.

        THIS RETURNED ``bool(sub.get("payment_token"))`` — a truthiness test on
        a string the subscriber wrote. It was True for every subscription that
        had ever been created, so every renewal "succeeded", the billing
        counters advanced and the period rolled forward on a schedule, with no
        payment gateway anywhere in this service.

        A BOOLEAN CANNOT CARRY THE ANSWER, which is why the return type changed.
        "The card was declined" and "there is no payment gateway configured" are
        both not-a-payment and they are NOT the same fact: the first belongs in
        a grace period that ends in cancellation, and doing that to the second
        would cancel a subscription for a charge nobody ever attempted.

        Returns a report with `status`:
            "paid"           the charge settled
            "declined"       the charge was attempted and refused
            "not_configured" no gateway — the outcome is not established
        """
        gateway = self.config.get("payment_gateway")
        if not gateway:
            return {
                "status": "not_configured",
                "settled": False,
                "value_moved": False,
                "reason": (
                    "no payment gateway is configured "
                    "(subscriptions.payment_gateway)"
                ),
            }
        if not sub.get("payment_token"):
            return {"status": "declined", "settled": False, "value_moved": False,
                    "reason": "no payment authorisation on file"}

        try:
            raw = await gateway.charge(
                token=sub["payment_token"],
                amount=self._plans[sub["plan_id"]]["price"],
                reference=sub["subscription_id"],
            )
        except Exception as exc:  # noqa: BLE001 — a transport fault is not a decline
            logger.error("Subscription %s charge raised: %s",
                         sub["subscription_id"], exc)
            return {"status": "unresolved", "settled": False, "value_moved": None,
                    "reason": f"the charge raised before reporting: {exc}"}

        # The gateway is a foreign structure, so its verdict is read with the
        # platform's own predicate rather than guessed from its wording, and
        # normalised into the three answers this service acts on.
        verdict = report_of(raw)
        if verdict is SUCCESS:
            return {"status": "paid", "settled": True, "value_moved": True,
                    "gateway_response": raw}
        if verdict is FAILURE:
            return {"status": "declined", "settled": False, "value_moved": False,
                    "reason": "the gateway refused the charge",
                    "gateway_response": raw}
        return {"status": "unresolved", "settled": False, "value_moved": None,
                "reason": "the gateway did not report an outcome",
                "gateway_response": raw}
