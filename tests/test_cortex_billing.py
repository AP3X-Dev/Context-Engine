"""Tests for ONI Cortex Stripe billing integration."""

import pytest
from unittest.mock import MagicMock, patch

from scripts.cortex.billing import (
    create_stripe_customer,
    create_subscription,
    PLAN_TO_PRICE_ID,
)


@pytest.mark.asyncio
@patch("scripts.cortex.billing.stripe")
async def test_create_stripe_customer(mock_stripe):
    mock_stripe.Customer.create = MagicMock(return_value=MagicMock(id="cus_test123"))
    customer_id = await create_stripe_customer("test@example.com", "Test Co")
    assert customer_id == "cus_test123"
    mock_stripe.Customer.create.assert_called_once_with(email="test@example.com", name="Test Co")


@pytest.mark.asyncio
@patch("scripts.cortex.billing.stripe")
async def test_create_subscription(mock_stripe):
    mock_stripe.Subscription.create = MagicMock(
        return_value=MagicMock(id="sub_test456", status="active")
    )
    sub = await create_subscription("cus_test123", "pro")
    assert sub.id == "sub_test456"


def test_plan_to_price_id_mapping():
    assert "pro" in PLAN_TO_PRICE_ID
    assert "team" in PLAN_TO_PRICE_ID
    assert "business" in PLAN_TO_PRICE_ID
    assert "enterprise" in PLAN_TO_PRICE_ID
    assert "free" not in PLAN_TO_PRICE_ID


@pytest.mark.asyncio
@patch("scripts.cortex.billing.stripe")
async def test_create_subscription_invalid_plan(mock_stripe):
    with pytest.raises(ValueError, match="No Stripe price"):
        await create_subscription("cus_test", "nonexistent_plan")
