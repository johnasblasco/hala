import smtplib

import pytest

from hala import mailer


class FakeSMTP:
    sent = []
    fail_login = False

    def __init__(self, host, port, timeout=0, context=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


CFG = {"user": "me@gmail.com", "password": "abcdabcdabcdabcd", "host": "smtp.gmail.com", "port": 465, "limit": 25}


def test_send_plain_text_from_own_mailbox():
    FakeSMTP.sent.clear()
    mailer.send_email(CFG, "owner@clinic.ph", "quick note", "Hello\n\nNot interested? Reply no thanks.",
                      "Johnas Blasco", _smtp=FakeSMTP)
    msg = FakeSMTP.sent[0]
    assert msg["From"] == "Johnas Blasco <me@gmail.com>" and msg["To"] == "owner@clinic.ph"
    assert msg["Reply-To"] == "me@gmail.com" and msg.get_content_type() == "text/plain"


def test_friendly_errors():
    FakeSMTP.fail_login = True
    with pytest.raises(mailer.MailError, match="App Password"):
        mailer.send_email(CFG, "a@b.co", "s", "b", _smtp=FakeSMTP)
    FakeSMTP.fail_login = False
    with pytest.raises(mailer.MailError, match="doesn't look like an email"):
        mailer.send_email(CFG, "not-an-email", "s", "b", _smtp=FakeSMTP)


def test_app_password_shape():
    assert mailer.looks_like_gmail_app_password("abcd efgh ijkl mnop")
    assert not mailer.looks_like_gmail_app_password("MyNormalPassw0rd!")
    assert mailer.mail_config({"smtp_user": "me@gmail.com"}) is None
