"""
Stripe integration for TopiCross's paid tier (recurring subscription via
Stripe Checkout, hosted on Stripe's side -- no card data ever touches our
server or frontend).

REQUIRED SETUP (done once, in the Stripe Dashboard, not in code):
  1. Create a Product ("TopiCross Paid") with a recurring Price attached
     to it. Copy that Price's ID (starts with "price_...").
  2. Create a webhook endpoint pointing at
     https://<your-backend>/stripe_webhook, subscribed to at least:
       - checkout.session.completed
       - customer.subscription.updated
       - customer.subscription.deleted
       - invoice.payment_failed
     Copy the webhook's signing secret (starts with "whsec_...").
  3. Set these on Render (Environment tab):
       STRIPE_SECRET_KEY      = sk_live_... (or sk_test_... while testing)
       STRIPE_PRICE_ID        = price_...
       STRIPE_WEBHOOK_SECRET  = whsec_...

Until STRIPE_SECRET_KEY is set, every function here raises a clear
RuntimeError rather than silently failing -- there's no safe "fallback"
mode for payments the way there was for email (log-only doesn't make
sense for money), so this fails loudly and immediately instead.
"""
import os
import stripe


def _require_configured():
    api_key = os.environ.get("STRIPE_SECRET_KEY")
    if not api_key:
        raise RuntimeError(
            "STRIPE_SECRET_KEY is not set -- Stripe billing isn't "
            "configured yet. See stripe_service.py's module docstring "
            "for setup steps."
        )
    stripe.api_key = api_key


def get_or_create_customer(user, db) -> str:
    """Returns the user's Stripe customer ID, creating one on first use.
    Reused on every subsequent checkout/portal call for this user rather
    than creating a new Stripe customer every time."""
    _require_configured()

    if user.stripe_customer_id:
        return user.stripe_customer_id

    customer = stripe.Customer.create(
        email=user.email,
        metadata={"user_id": str(user.id)},
    )
    user.stripe_customer_id = customer.id
    db.add(user)
    db.commit()
    return customer.id


def create_checkout_session(user, db, frontend_url: str) -> str:
    """Creates a Stripe Checkout session for the recurring subscription
    price and returns the hosted URL to redirect the user's browser to.

    success_url / cancel_url both point back at the frontend root --
    the frontend itself doesn't need to DO anything different for
    success vs. cancel (no card details ever reach it either way), it
    just re-checks the user's tier from /me on load. The real tier flip
    happens via the checkout.session.completed webhook, not this
    redirect -- Stripe can deliver the webhook slightly before or after
    the browser redirect happens, so the frontend shouldn't assume
    "success" here means the tier is flipped yet.
    """
    _require_configured()

    price_id = os.environ.get("STRIPE_PRICE_ID")
    if not price_id:
        raise RuntimeError("STRIPE_PRICE_ID is not set -- see stripe_service.py.")

    customer_id = get_or_create_customer(user, db)

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{frontend_url}?checkout=success",
        cancel_url=f"{frontend_url}?checkout=cancelled",
        # Lets a user who somehow already has an active subscription
        # (e.g. double-clicked "Upgrade" in two tabs) get redirected to
        # the billing portal instead of creating a duplicate one.
        client_reference_id=str(user.id),
    )
    return session.url


def create_billing_portal_session(user, frontend_url: str) -> str:
    """Creates a Stripe Billing Portal session so a subscribed user can
    view invoices, update their card, or cancel -- entirely on Stripe's
    side, without needing any of that logic built here."""
    _require_configured()

    if not user.stripe_customer_id:
        raise RuntimeError(
            "This user has no Stripe customer yet -- they've never "
            "started a checkout, so there's no billing portal to show."
        )

    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=frontend_url,
    )
    return session.url


def cancel_subscription(subscription_id: str):
    """Cancels a subscription immediately (not at period end) -- used
    when a user deletes their account entirely, since there's no longer
    a user record for a later webhook to apply an end-of-period
    cancellation to. A user who just wants to stop paying but keep their
    account should use the billing portal instead, which defaults to
    Stripe's own cancel-at-period-end flow."""
    _require_configured()
    stripe.Subscription.delete(subscription_id)


def verify_webhook(payload: bytes, sig_header: str):
    """Verifies a webhook request actually came from Stripe (not a
    forged request hitting our public /stripe_webhook endpoint) using
    the signing secret. Raises stripe.error.SignatureVerificationError
    on failure -- the caller (main.py) turns that into a 400, which is
    deliberately NOT swallowed, the same principle as email_service.py's
    send failures: a rejected webhook should be visible in logs, not
    silently ignored, since ignoring it here means a real payment event
    (e.g. a cancellation) never reaches our database."""
    _require_configured()

    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is not set -- see stripe_service.py.")

    return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
