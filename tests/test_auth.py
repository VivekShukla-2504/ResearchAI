from datetime import datetime, timezone
import json
from unittest.mock import MagicMock, patch

import pytest

from researchpaper_ai.auth import (
    create_jwt,
    decode_jwt,
    generate_otp,
    hash_password,
    send_otp_email,
    verify_google_id_token,
    verify_password,
)


def test_password_hashing_and_verification():
    pwd = "super_secure_research_password_2026"
    h = hash_password(pwd)
    assert h.startswith("pbkdf2:sha256:100000$")
    assert verify_password(pwd, h) is True
    assert verify_password("wrong_password", h) is False
    assert verify_password("", h) is False
    assert verify_password(pwd, "invalid$format") is False
    assert verify_password(pwd, None) is False


def test_jwt_generation_and_decoding():
    secret = "test_super_secret_jwt_key_42"
    payload = {"user_id": "user_abc123", "email": "researcher@example.edu", "name": "Dr. Smith"}

    token = create_jwt(payload, secret, expires_in_seconds=3600)
    assert isinstance(token, str)
    assert len(token.split(".")) == 3

    decoded = decode_jwt(token, secret)
    assert decoded is not None
    assert decoded["user_id"] == "user_abc123"
    assert decoded["email"] == "researcher@example.edu"
    assert decoded["name"] == "Dr. Smith"

    # Wrong secret
    assert decode_jwt(token, "wrong_secret_key") is None

    # Tampered signature
    parts = token.split(".")
    tampered = f"{parts[0]}.{parts[1]}.tamperedsig"
    assert decode_jwt(tampered, secret) is None

    # Expired token
    expired_token = create_jwt(payload, secret, expires_in_seconds=-10)
    assert decode_jwt(expired_token, secret) is None


def test_otp_generation():
    otp = generate_otp(6)
    assert len(otp) == 6
    assert otp.isdigit()

    # Randomness check
    otps = {generate_otp(6) for _ in range(50)}
    assert len(otps) > 40


def test_send_otp_email_mocked():
    with patch("smtplib.SMTP") as mock_smtp_class:
        mock_server = MagicMock()
        mock_smtp_class.return_value = mock_server

        success = send_otp_email(
            "student@university.edu",
            "654321",
            "signup",
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="noreply@example.com",
            smtp_pass="app_password",
        )
        assert success is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("noreply@example.com", "app_password")
        mock_server.sendmail.assert_called_once()
        mock_server.quit.assert_called_once()


def test_google_token_verification_success():
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__.return_value = mock_response
    mock_response.read.return_value = json.dumps({
        "iss": "https://accounts.google.com",
        "aud": "my-google-client-id",
        "sub": "google-user-999",
        "email": "scholar@gmail.com",
        "email_verified": True,
        "name": "Prof. Scholar",
        "picture": "https://lh3.googleusercontent.com/avatar",
    }).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=mock_response):
        info = verify_google_id_token("mock_google_id_token", expected_client_id="my-google-client-id")
        assert info is not None
        assert info["email"] == "scholar@gmail.com"
        assert info["name"] == "Prof. Scholar"
        assert info["google_id"] == "google-user-999"


def test_google_token_verification_mismatch_and_invalid():
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__.return_value = mock_response
    mock_response.read.return_value = json.dumps({
        "iss": "https://fake.issuer.com",
        "aud": "wrong-client-id",
        "email": "attacker@evil.com",
    }).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=mock_response):
        assert verify_google_id_token("mock_token", expected_client_id="my-google-client-id") is None
