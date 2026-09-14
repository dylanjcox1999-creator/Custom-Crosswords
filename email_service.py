"""
Sends the password-reset email via Resend (https://resend.com), with an
HONEST FALLBACK to console-logging the link when Resend isn't configured.

CRITICAL LIMITATION, confirmed directly against Resend's current docs
(not assumed from memory): the no-setup sender address
"onboarding@resend.dev" can ONLY deliver to the Resend account owner's
own verified email address -- it will return a 403 error for any other
recipient. This means, until a real domain is verified with Resend:

  - You (the account owner) CAN successfully test this end-to-end by
    requesting a reset for your own account email
  - Real users signing up with a DIFFERENT email will NOT receive
    anything -- the send will fail with a 403 from Resend's API

To actually email real users, verify a domain you own in the Resend
dashboard (Domains -> Add Domain), add the DNS records Resend gives you
at your domain's DNS provider, wait for verification, then set
RESEND_FROM_ADDRESS to an address on that domain (e.g.
"noreply@yourdomain.com"). This project doesn't own a domain yet as of
this writing -- that's a real, separate decision (and cost) from just
adding an API key.

Uses a plain HTTP POST via `requests` (already a dependency) rather than
adding the `resend` SDK package, to keep the dependency footprint small
for what is, under the hood, a single simple API call.
"""
import os
import requests

RESEND_API_URL = "https://api.resend.com/emails"


def send_reset_email(to_email: str, reset_link: str) -> bool:
    """
    Attempts to send a password reset email via Resend. Returns True if
    the email was actually sent, False if it fell through to the
    log-only fallback (no RESEND_API_KEY configured).

    Raises requests.HTTPError if Resend's API rejects the request (for
    example, a 403 because the recipient isn't the account owner's own
    email and no domain is verified yet -- see the module docstring).
    Deliberately does NOT swallow this error into a silent log-fallback:
    a failed real send should surface as a real error to whoever's
    monitoring the backend, not disappear silently the way it would if
    treated the same as "no provider configured at all."
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        # Honest fallback: no real email provider configured. Print the
        # link so a developer/admin watching Render's logs can manually
        # relay it. SECURITY NOTE: this logging is acceptable ONLY
        # because it's the sole delivery mechanism when no real provider
        # exists -- once RESEND_API_KEY is set, this branch is never
        # reached, and the link is never logged.
        print(
            f"[PASSWORD RESET -- NO EMAIL SERVICE CONFIGURED] "
            f"Reset link for {to_email}: {reset_link} (expires in 30 minutes). "
            f"This was printed instead of emailed -- see email_service.py."
        )
        return False

    from_address = os.environ.get("RESEND_FROM_ADDRESS", "onboarding@resend.dev")

    response = requests.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": from_address,
            "to": [to_email],
            "subject": "Reset your TopiCross password",
            "html": (
                f"<p>Someone requested a password reset for this account. "
                f"If that was you, click below:</p>"
                f"<p><a href='{reset_link}'>{reset_link}</a></p>"
                f"<p>This link expires in 30 minutes. If you didn't request "
                f"this, you can safely ignore this email.</p>"
            ),
        },
        timeout=10,
    )
    response.raise_for_status()  # raises if Resend rejects the request (e.g. 403)
    return True


def send_welcome_email(to_email: str, display_name: str, bonus_generations: int = 0) -> bool:
    """
    Attempts to send a welcome email via Resend right after signup.
    Returns True if actually sent, False if it fell through to the
    log-only fallback (no RESEND_API_KEY configured) -- same honest-
    fallback shape as send_reset_email above, for the same reason: this
    is a nice-to-have, not something that should ever block or fail a
    signup if email delivery has a problem (see how /signup in main.py
    calls this -- wrapped in try/except, failure only logged).

    Unlike the reset email, there's no security-sensitive content here
    (no token, no link that grants access) -- purely a courtesy message,
    so a failed send is lower-stakes than a failed reset email, but
    still handled the same way for consistency.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print(
            f"[WELCOME EMAIL -- NO EMAIL SERVICE CONFIGURED] "
            f"Would have welcomed {to_email} ({display_name}). "
            f"This was printed instead of emailed -- see email_service.py."
        )
        return False

    from_address = os.environ.get("RESEND_FROM_ADDRESS", "onboarding@resend.dev")

    bonus_line = (
        f"<p>As a bonus, {bonus_generations} free puzzle generation"
        f"{'s' if bonus_generations != 1 else ''} carried over from your "
        f"trial straight into your new account.</p>"
        if bonus_generations > 0 else ""
    )

    response = requests.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": from_address,
            "to": [to_email],
            "subject": "Welcome to TopiCross",
            "html": (
                f"<p>Hi {display_name},</p>"
                f"<p>Welcome to TopiCross -- crossword puzzles generated on "
                f"any topic you want, plus a real daily puzzle grounded in "
                f"actual historical events.</p>"
                f"{bonus_line}"
                f"<p>Jump back in any time at "
                f"<a href='https://topicross.app'>topicross.app</a>.</p>"
                f"<p>Questions or feedback? Reach us at support@topicross.app.</p>"
            ),
        },
        timeout=10,
    )
    response.raise_for_status()
    return True


def send_deletion_email(to_email: str, display_name: str) -> bool:
    """
    Attempts to send an account-deletion confirmation email via Resend,
    right after a delete succeeds. Same honest-fallback shape as the
    other two functions in this file. Two real reasons this exists, not
    just a courtesy copy of the welcome email:

      1. A paper trail. If a user later disputes a charge or asks
         "did my account actually get deleted", a timestamped email
         (from Resend's own delivery logs, not just this app's database,
         which by definition no longer has the row to check) is real
         evidence the deletion happened and when.
      2. Account-takeover detection. If someone's account gets
         compromised and deleted without their knowledge, this email to
         their inbox -- sent to the email on file, not anywhere an
         attacker chose -- is the only way they'd find out it happened.

    Deliberately fire-and-forget from the caller's side (see how
    /delete_account in main.py calls this): a failed send should never
    block someone's ability to actually delete their account.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print(
            f"[DELETION EMAIL -- NO EMAIL SERVICE CONFIGURED] "
            f"Would have sent deletion confirmation to {to_email} ({display_name}). "
            f"This was printed instead of emailed -- see email_service.py."
        )
        return False

    from_address = os.environ.get("RESEND_FROM_ADDRESS", "onboarding@resend.dev")

    response = requests.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": from_address,
            "to": [to_email],
            "subject": "Your TopiCross account has been deleted",
            "html": (
                f"<p>Hi {display_name},</p>"
                f"<p>This confirms your TopiCross account and all associated "
                f"solve history have been permanently deleted, along with any "
                f"active subscription (no further charges will occur).</p>"
                f"<p>If you didn't request this, contact us immediately at "
                f"support@topicross.app.</p>"
                f"<p>You're welcome back any time at "
                f"<a href='https://topicross.app'>topicross.app</a> -- "
                f"just sign up again with the same or a different email.</p>"
            ),
        },
        timeout=10,
    )
    response.raise_for_status()
    return True
