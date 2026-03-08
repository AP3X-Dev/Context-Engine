"""Stripe billing integration for ONI Cortex."""

from __future__ import annotations
import os
from typing import Optional

import stripe
from scripts.cortex.config import STRIPE_SECRET_KEY

stripe.api_key = STRIPE_SECRET_KEY

# Map plan names to Stripe Price IDs (configure via env after creating products in Stripe)
PLAN_TO_PRICE_ID = {
    "pro": os.environ.get("STRIPE_PRICE_PRO", "price_pro_placeholder"),
    "team": os.environ.get("STRIPE_PRICE_TEAM", "price_team_placeholder"),
    "business": os.environ.get("STRIPE_PRICE_BUSINESS", "price_business_placeholder"),
    "enterprise": os.environ.get("STRIPE_PRICE_ENTERPRISE", "price_enterprise_placeholder"),
}


async def create_stripe_customer(email: str, name: str) -> str:
    """Create a Stripe customer and return their ID."""
    customer = stripe.Customer.create(email=email, name=name)
    return customer.id


async def create_subscription(customer_id: str, plan: str):
    """Create a Stripe subscription for the given plan."""
    price_id = PLAN_TO_PRICE_ID.get(plan)
    if not price_id:
        raise ValueError(f"No Stripe price configured for plan: {plan}")
    return stripe.Subscription.create(customer=customer_id, items=[{"price": price_id}])


async def cancel_subscription(subscription_id: str):
    """Cancel a Stripe subscription."""
    return stripe.Subscription.delete(subscription_id)


async def get_subscription(subscription_id: str):
    """Get subscription details."""
    return stripe.Subscription.retrieve(subscription_id)


def verify_webhook_signature(payload: bytes, sig_header: str, secret: str) -> dict:
    """Verify a Stripe webhook signature and return the event."""
    return stripe.Webhook.construct_event(payload, sig_header, secret)
