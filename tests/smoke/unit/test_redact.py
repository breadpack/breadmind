from breadmind.smoke._redact import redact_secrets


def test_redacts_slack_bot_token():
    raw = "token=xoxb-123-abc-DEFGHIJK"
    assert "xoxb-123-abc-DEFGHIJK" not in redact_secrets(raw)


def test_redacts_atlassian_token():
    raw = "Authorization: Basic user@x.com:ATATT3xFfGF0abcdefghijklmnop0123456789"
    out = redact_secrets(raw)
    assert "ATATT3xFfGF0abcdefghijklmnop0123456789" not in out
    assert "user@x.com" not in out


def test_redacts_anthropic_key():
    raw = "x-api-key: sk-ant-api01-AAAA-BBBB-CCCC"
    assert "sk-ant-api01-AAAA-BBBB-CCCC" not in redact_secrets(raw)


def test_redacts_aws_access_key_id():
    raw = "AKIAIOSFODNN7EXAMPLE is the access key"
    assert "AKIAIOSFODNN7EXAMPLE" not in redact_secrets(raw)


def test_redacts_bearer_header():
    raw = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"
    assert "eyJhbGciOiJIUzI1NiJ9.payload.sig" not in redact_secrets(raw)


def test_passthrough_plain_text():
    raw = "the migration is at head 006_connector_configs"
    assert redact_secrets(raw) == raw


def test_truncates_to_cap():
    raw = "x" * 10_000
    assert len(redact_secrets(raw)) <= 400
