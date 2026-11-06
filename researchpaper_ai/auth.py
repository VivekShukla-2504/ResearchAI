"""Authentication, JWT tokens, password hashing, Google OAuth, and SMTP OTP dispatch."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any
import urllib.request
import urllib.parse

logger = logging.getLogger("researchpaper_ai.auth")


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with a unique random salt."""
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return f"pbkdf2:sha256:100000${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    """Verify password against stored PBKDF2 hash using constant-time comparison."""
    if not stored_hash or not stored_hash.startswith("pbkdf2:sha256:"):
        return False
    try:
        header, salt_hex, expected_hex = stored_hash.split("$")
        _, _, iterations_str = header.split(":")
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual.hex(), expected_hex)
    except Exception:
        return False


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = 4 - (len(data) % 4)
    if padding and padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data.encode("ascii"))


def create_jwt(payload: dict[str, Any], secret: str, expires_in_seconds: int = 7 * 86400) -> str:
    """Create a standard HS256 JWT."""
    now = int(time.time())
    token_payload = dict(payload)
    token_payload.setdefault("iat", now)
    token_payload.setdefault("exp", now + expires_in_seconds)

    header = {"alg": "HS256", "typ": "JWT"}
    b64_header = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    b64_payload = _b64url_encode(json.dumps(token_payload, separators=(",", ":")).encode("utf-8"))

    signing_input = f"{b64_header}.{b64_payload}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    b64_sig = _b64url_encode(signature)

    return f"{b64_header}.{b64_payload}.{b64_sig}"


def decode_jwt(token: str, secret: str) -> dict[str, Any] | None:
    """Decode and verify an HS256 JWT. Returns payload if valid, None if invalid or expired."""
    try:
        parts = token.strip().split(".")
        if len(parts) != 3:
            return None
        b64_header, b64_payload, b64_sig = parts

        signing_input = f"{b64_header}.{b64_payload}".encode("ascii")
        expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        actual_sig = _b64url_decode(b64_sig)

        if not hmac.compare_digest(actual_sig, expected_sig):
            return None

        payload_bytes = _b64url_decode(b64_payload)
        payload = json.loads(payload_bytes.decode("utf-8"))

        # Check expiration
        exp = payload.get("exp")
        if exp is not None and int(exp) < int(time.time()):
            logger.info("JWT token has expired")
            return None

        return payload
    except Exception as exc:
        logger.debug("Failed to decode JWT: %s", exc)
        return None


def generate_otp(length: int = 6) -> str:
    """Generate a cryptographically secure random numeric OTP."""
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def verify_google_id_token(id_token: str, expected_client_id: str | None = None) -> dict[str, Any] | None:
    """Verify Google OAuth ID token using Google's tokeninfo API."""
    try:
        url = f"https://oauth2.googleapis.com/tokeninfo?id_token={urllib.parse.quote(id_token)}"
        req = urllib.request.Request(url, headers={"User-Agent": "ResearchPaperAI-Auth"})
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status != 200:
                return None
            data = json.loads(response.read().decode("utf-8"))

        # Validate issuer
        if data.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
            logger.warning("Google token issuer mismatch: %s", data.get("iss"))
            return None

        # Validate audience if client ID is configured
        if expected_client_id and data.get("aud") != expected_client_id:
            logger.warning("Google token audience mismatch: %s vs %s", data.get("aud"), expected_client_id)
            return None

        email = data.get("email")
        if not email:
            return None

        return {
            "email": email.strip().lower(),
            "name": data.get("name") or email.split("@")[0],
            "picture": data.get("picture"),
            "google_id": data.get("sub"),
            "email_verified": data.get("email_verified") in (True, "true"),
        }
    except Exception as exc:
        logger.warning("Google ID token verification failed: %s", exc)
        return None


def send_otp_email(
    to_email: str,
    otp: str,
    purpose: str = "signup",
    *,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    smtp_user: str | None = None,
    smtp_pass: str | None = None,
    mail_from: str | None = None,
) -> bool:
    """Send an automated OTP email via SMTP with professional HTML styling."""
    host = smtp_host or os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = smtp_port or int(os.getenv("SMTP_PORT", "587"))
    user = smtp_user or os.getenv("SMTP_USER", "")
    password = smtp_pass or os.getenv("SMTP_PASS", "")
    sender = mail_from or os.getenv("MAIL_FROM", user)

    purpose_titles = {
        "signup": "Verify your email for ResearchPaper AI",
        "login": "Your ResearchPaper AI login verification code",
        "reset_password": "Reset your ResearchPaper AI password",
    }
    subject = purpose_titles.get(purpose, "Your ResearchPaper AI verification code")

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0b1022; color: #edf0ff; margin: 0; padding: 32px 16px; }}
        .card {{ max-width: 480px; margin: 0 auto; background: #151b31; border: 1px solid #282f4d; border-radius: 14px; padding: 32px; box-shadow: 0 16px 36px rgba(0,0,0,0.3); }}
        .header {{ text-align: center; margin-bottom: 24px; }}
        .logo {{ font-size: 20px; font-weight: 700; color: #aaa0ff; letter-spacing: -0.5px; }}
        .title {{ font-size: 18px; font-weight: 600; color: #edf0ff; margin: 16px 0 8px; }}
        .text {{ font-size: 13px; color: #9ba3c2; line-height: 1.6; margin: 0 0 20px; text-align: center; }}
        .otp-box {{ background: #211f43; border: 2px dashed #aaa0ff; border-radius: 10px; padding: 18px; text-align: center; margin: 24px 0; }}
        .otp-code {{ font-family: 'Courier New', Courier, monospace; font-size: 32px; font-weight: 700; letter-spacing: 8px; color: #c5bfff; }}
        .footer {{ font-size: 11px; color: #7f88a9; text-align: center; margin-top: 24px; line-height: 1.5; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="header">
          <div class="logo">✦ ResearchPaper AI</div>
          <div class="title">{subject}</div>
          <p class="text">Use the 6-digit verification code below to complete your authentication.</p>
        </div>
        <div class="otp-box">
          <div class="otp-code">{otp}</div>
        </div>
        <p class="text" style="font-size: 11px; color: #7f88a9;">This code is valid for 10 minutes. If you did not request this code, you can safely ignore this email.</p>
        <div class="footer">
          ResearchPaper AI · Advanced Academic Discovery Platform<br>
          Sent securely to {to_email}
        </div>
      </div>
    </body>
    </html>
    """

    text_content = f"Your ResearchPaper AI verification code is: {otp}\n\nThis code expires in 10 minutes.\nIf you did not request this, please ignore this email."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"ResearchPaper AI <{sender}>"
    msg["To"] = to_email

    msg.attach(MIMEText(text_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    if not host or not user or not password:
        logger.warning("SMTP credentials missing; cannot send email. OTP for %s: %s", to_email, otp)
        print(f"\n[DEV MODE OTP] Email: {to_email} | Purpose: {purpose} | OTP: {otp}\n")
        return True

    try:
        server = smtplib.SMTP(host, port, timeout=10)
        server.starttls()
        server.login(user, password)
        server.sendmail(sender, [to_email], msg.as_string())
        server.quit()
        logger.info("Successfully sent OTP email to %s", to_email)
        return True
    except Exception as exc:
        logger.error("Failed to send SMTP email to %s: %s", to_email, exc)
        print(f"\n[DEV FALLBACK OTP] Email: {to_email} | Purpose: {purpose} | OTP: {otp}\n")
        return False
