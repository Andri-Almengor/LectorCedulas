from assets.runtime.hardened.privacy import redact_text, technical_event


def test_logs_redact_identifier_token_and_query():
    text = redact_text("cedula 1-2345-6789 https://x.test/path?token=secret token=abc")
    assert "2345" not in text
    assert "secret" not in text
    assert "abc" not in text
    assert "?" not in text


def test_technical_event_drops_unapproved_fields():
    event = technical_event("scan", sequence_id=1, Nombre="PERSONA REAL", target_pid=42)
    assert "PERSONA REAL" not in event
    assert '"sequence_id": "1"' in event
