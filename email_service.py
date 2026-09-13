"""
Sends the password-reset email. This is a pluggable interface with an
HONEST FALLBACK, not a working email integration -- there is currently no
email-sending service (SendGrid, Resend, Mailgun, AWS SES, etc.) wired
into this project.

Without EMAIL_SERVICE configured, reset links are printed to the server
log instead of emailed. This means /forgot_password currently only works
if you (or whoever has access to Render's logs) manually relay the link
to the user -- it is NOT a working self-service flow yet. This is
deliberate honesty, not a bug: pretending email delivery works when it
doesn't would be worse than clearly marking the gap.

To make this a real working feature, pick an email provider, get an API
key, and implement send_reset_email() below to actually call that
provider's API instead of falling through to the log-only fallback.
Reasonable options as of this writing: Resend, SendGrid, Mailgun, AWS
SES -- pricing and free-tier terms change, so check current offerings
rather than assume anything stated in an older reference is still
accurate.
"""
import os


def send_reset_email(to_email: str, reset_link: str) -> bool:
    """
    Attempts to send a password reset email. Returns True if a real send
    was attempted (regardless of provider-side success/failure, which
    would need provider-specific error handling once one is wired in),
    False if it fell through to the log-only fallback.

    SECURITY NOTE for whoever wires in a real provider: do not log
    reset_link in production once real email sending works -- the
    console-log fallback below is acceptable ONLY because it is
    explicitly the sole delivery mechanism when no real provider is
    configured. Once a real provider exists, logging the link
    alongside a real send would defeat the purpose of emailing it
    privately in the first place.
    """
    if os.environ.get("EMAIL_SERVICE") == "resend" and os.environ.get("RESEND_API_KEY"):
        # Not implemented -- placeholder for wiring in a real provider.
        # Example shape (untested, Resend's API may have changed):
        #   import requests
        #   requests.post(
        #       "https://api.resend.com/emails",
        #       headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
        #       json={
        #           "from": "noreply@yourdomain.com",
        #           "to": to_email,
        #           "subject": "Reset your password",
        #           "html": f"<p>Click to reset your password: <a href='{reset_link}'>{reset_link}</a></p>"
        #                   f"<p>This link expires in 30 minutes.</p>",
        #       },
        #   )
        raise NotImplementedError(
            "EMAIL_SERVICE=resend is set but send_reset_email() doesn't actually "
            "call Resend's API yet -- fill in the real implementation above."
        )

    # Honest fallback: no real email provider configured. Print the link
    # so a developer/admin watching Render's logs can manually relay it.
    print(
        f"[PASSWORD RESET -- NO EMAIL SERVICE CONFIGURED] "
        f"Reset link for {to_email}: {reset_link} (expires in 30 minutes). "
        f"This was printed instead of emailed -- see email_service.py."
    )
    return False
