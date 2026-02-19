import pytest
from unittest.mock import MagicMock, patch, ANY
import os
from backend.server.services.email_service import EmailService, get_email_service

@pytest.fixture
def email_service():
    return EmailService(
        smtp_host="localhost",
        smtp_port=587,
        smtp_user="test@example.com",
        smtp_password="password",
        from_email="noreply@forge.ai"
    )

def test_email_service_enabled_status():
    # Enabled
    svc = EmailService(smtp_host="h", smtp_user="u", smtp_password="p")
    assert svc.enabled is True
    
    # Disabled (missing password)
    svc2 = EmailService(smtp_host="h", smtp_user="u", smtp_password=None)
    assert svc2.enabled is False

@patch("smtplib.SMTP")
def test_send_email_success(mock_smtp_class, email_service):
    mock_server = MagicMock()
    mock_smtp_class.return_value.__enter__.return_value = mock_server
    
    result = email_service.send_email(
        to_email="user@test.com",
        subject="Test Sub",
        html_body="<h1>Hello</h1>",
        text_body="Hello"
    )
    
    assert result is True
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("test@example.com", "password")
    mock_server.send_message.assert_called_once()
    
    # Check message construction
    msg = mock_server.send_message.call_args[0][0]
    assert msg["To"] == "user@test.com"
    assert msg["Subject"] == "Test Sub"
    # It's a MIMEMultipart with 2 parts
    assert len(msg.get_payload()) == 2

@patch("smtplib.SMTP")
def test_send_email_failure(mock_smtp_class, email_service):
    mock_smtp_class.side_effect = Exception("SMTP Error")
    
    result = email_service.send_email("u@t.com", "S", "H")
    assert result is False

def test_send_email_not_configured():
    svc = EmailService(smtp_host=None) # disabled
    assert svc.send_email("a", "b", "c") is False

@patch.object(EmailService, "send_email")
def test_send_password_reset_email_url_construction(mock_send, email_service):
    mock_send.return_value = True
    
    with patch.dict(os.environ, {"APP_BASE_URL": "https://forge.ai"}):
        email_service.send_password_reset_email(
            to_email="user@test.com",
            reset_token="secret-token"
        )
    
    # Verify the URL in the call
        args, kwargs = mock_send.call_args
        to_email = args[0]
        subject = args[1]
        html_body = args[2]
        
        assert to_email == "user@test.com"
        assert "https://forge.ai/auth/reset-password" in html_body
        assert "token=secret-token" in html_body
        assert "user%40test.com" in html_body  # urlencoded email
def test_get_email_service_singleton():
    svc1 = get_email_service()
    svc2 = get_email_service()
    assert svc1 is svc2
