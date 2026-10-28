"""Emails an immediate alert when Pinterest or Instagram stops accepting our sign-in, instead of
waiting for the nightly digest. One alert per service per 12 hours, so an outage can't flood the inbox."""
import datetime as dt
import json
import re
from pathlib import Path

SENT_PATH = Path(__file__).parent.parent / "data" / "alerts_sent.json"
QUIET_HOURS = 12

# signs that the sign-in itself is the problem (not a one-off hiccup with a single photo or listing)
AUTH_PATTERN = re.compile(
    r"returned 401|Token (refresh|exchange) failed|invalid_grant|OAuthException|\"code\": ?190|access token|"
    r"could not sign in|session has (expired|been invalidated)", re.I)

FIXES = {
    "Pinterest": "Pinterest sign-in usually fails after a Pinterest password change or if the app's access was removed. "
                 "Reconnecting it takes a few minutes with Claude's help.",
    "Instagram": "Instagram sign-in usually fails after a password change, a security prompt, or if the app's access was removed. "
                 "Reconnecting it takes a few minutes with Claude's help.",
}


def is_auth_failure(error):
    return bool(AUTH_PATTERN.search(str(error)))


def alert(service, error, log=print):
    """Send the alert unless one for this service already went out recently. Never raises."""
    try:
        now = dt.datetime.now(dt.timezone.utc)
        sent = json.loads(SENT_PATH.read_text()) if SENT_PATH.exists() else {}
        last = sent.get(service)
        if last and now - dt.datetime.fromisoformat(last) < dt.timedelta(hours=QUIET_HOURS):
            log(f"{service} sign-in alert already sent recently; not sending another.")
            return
        from .notify import send_email
        subject = f"Action needed: {service} sign-in has stopped working"
        detail = str(error)[:300]
        plain = (f"AutoWittenberg could not sign in to {service}, so posting there is paused until it is reconnected.\n\n"
                 f"{FIXES[service]}\n\nTechnical detail: {detail}\n\nYou will get at most one of these every {QUIET_HOURS} hours.")
        html = ("<div style='font-family:Helvetica,Arial,sans-serif;max-width:560px;margin:10px auto;font-size:15px;color:#2b1b0e'>"
                f"<div style='background:#7a1f2b;color:#f4e3c1;padding:14px 18px;border-radius:8px 8px 0 0;font-size:18px'>"
                f"<b>{service} sign-in has stopped working</b></div>"
                "<div style='border:1px solid #e0d2b8;border-top:0;padding:16px 18px;border-radius:0 0 8px 8px'>"
                f"<p>AutoWittenberg could not sign in to {service}, so posting there is paused until it is reconnected.</p>"
                f"<p>{FIXES[service]}</p>"
                f"<p style='color:#777;font-size:12px'>Technical detail: {detail}</p>"
                f"<p style='color:#777;font-size:12px'>You will get at most one of these every {QUIET_HOURS} hours.</p></div></div>")
        send_email(subject, plain, html)
        sent[service] = now.isoformat()
        SENT_PATH.write_text(json.dumps(sent) + "\n")
        log(f"Sent an alert email about {service} sign-in.")
    except Exception as e:
        log(f"Could not send the {service} alert email: {e}")
