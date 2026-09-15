from app.services import smtp_email


class FakeClient:
    def __init__(self):
        self.login_args = None
        self.message = None
        self.starttls_context = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, message):
        self.message = message

    def starttls(self, *, context):
        self.starttls_context = context


def test_smtps_decodes_credentials_once_and_uses_verified_context(monkeypatch):
    client = FakeClient()
    context = object()
    captured = {}

    def smtp_ssl(host, port, *, timeout, context):
        captured.update(host=host, port=port, timeout=timeout, context=context)
        return client

    monkeypatch.setattr(smtp_email.ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(smtp_email.smtplib, "SMTP_SSL", smtp_ssl)

    sender = smtp_email.SmtpEmailSender(
        "smtps://res%65nd:token%252Fpart@smtp.resend.com:465",
        "Flare <no-reply@flare4u.tech>",
    )
    sender.send(to="user@example.com", subject="Verify", text="hello")

    assert captured == {
        "host": "smtp.resend.com",
        "port": 465,
        "timeout": 10,
        "context": context,
    }
    assert client.login_args == ("resend", "token%2Fpart")
    assert client.message["From"] == "Flare <no-reply@flare4u.tech>"
    assert client.message["To"] == "user@example.com"


def test_starttls_uses_verified_context_and_decoded_password(monkeypatch):
    client = FakeClient()
    context = object()
    captured = {}

    def smtp(host, port, *, timeout):
        captured.update(host=host, port=port, timeout=timeout)
        return client

    monkeypatch.setattr(smtp_email.ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(smtp_email.smtplib, "SMTP", smtp)

    sender = smtp_email.SmtpEmailSender(
        "smtp://resend:a%40b%3Ac@smtp.resend.com:587",
        "Flare <no-reply@flare4u.tech>",
    )
    sender.send(to="user@example.com", subject="Verify", text="hello")

    assert captured == {"host": "smtp.resend.com", "port": 587, "timeout": 10}
    assert client.starttls_context is context
    assert client.login_args == ("resend", "a@b:c")


def test_smtp_defaults_ports_by_tls_mode(monkeypatch):
    ssl_client = FakeClient()
    starttls_client = FakeClient()
    context = object()
    ports = []

    monkeypatch.setattr(smtp_email.ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(
        smtp_email.smtplib,
        "SMTP_SSL",
        lambda host, port, *, timeout, context: ports.append(("smtps", port)) or ssl_client,
    )
    monkeypatch.setattr(
        smtp_email.smtplib,
        "SMTP",
        lambda host, port, *, timeout: ports.append(("smtp", port)) or starttls_client,
    )

    smtp_email.SmtpEmailSender("smtps://smtp.example.com", "noreply@example.com").send(
        to="user@example.com", subject="A", text="A"
    )
    smtp_email.SmtpEmailSender("smtp://smtp.example.com", "noreply@example.com").send(
        to="user@example.com", subject="B", text="B"
    )

    assert ports == [("smtps", 465), ("smtp", 587)]


def test_invalid_smtp_scheme_is_rejected():
    try:
        smtp_email.SmtpEmailSender("https://smtp.example.com", "noreply@example.com")
    except ValueError as error:
        assert "smtp:// or smtps://" in str(error)
    else:
        raise AssertionError("invalid SMTP scheme was accepted")
