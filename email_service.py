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
    print(
        f"[DEBUG send_reset_email] pid={os.getpid()} "
        f"api_key_present={api_key is not None} "
        f"api_key_len={len(api_key) if api_key else 0} "
        f"from_address={os.environ.get('RESEND_FROM_ADDRESS', '(not set)')}"
    )
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
            "subject": "Reset your Custom Crosswords Daily password",
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
