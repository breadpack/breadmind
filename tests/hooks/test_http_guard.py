import pytest
from breadmind.hooks.http_guard import validate_url, SSRFError


def test_allow_public_https():
    validate_url("https://example.com/webhook")


def test_block_localhost():
    with pytest.raises(SSRFError, match="private"):
        validate_url("http://127.0.0.1/hook")


def test_block_private_10():
    with pytest.raises(SSRFError, match="private"):
        validate_url("https://10.0.0.1/hook")


def test_block_private_172():
    with pytest.raises(SSRFError, match="private"):
        validate_url("https://172.16.0.1/hook")


def test_block_private_192():
    with pytest.raises(SSRFError, match="private"):
        validate_url("https://192.168.1.1/hook")


def test_block_link_local():
    with pytest.raises(SSRFError, match="private"):
        validate_url("https://169.254.169.254/latest/meta-data/")


def test_block_http_by_default():
    with pytest.raises(SSRFError, match="HTTPS"):
        validate_url("http://example.com/webhook")


def test_allow_http_when_permitted():
    validate_url("http://example.com/webhook", allow_http=True)


def test_allowed_hosts_strict_pass():
    validate_url("https://hooks.slack.com/x", allowed_hosts=["hooks.slack.com"])


def test_allowed_hosts_strict_fail():
    with pytest.raises(SSRFError, match="not in allowed"):
        validate_url("https://evil.com/x", allowed_hosts=["hooks.slack.com"])


def test_block_ipv6_loopback():
    with pytest.raises(SSRFError, match="private"):
        validate_url("https://[::1]/hook")


def test_allow_public_ip():
    validate_url("https://8.8.8.8/hook")
