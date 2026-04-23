from breadmind.web.auth import AuthManager


def test_create_session_stores_username():
    am = AuthManager(password_hash=AuthManager.hash_password("p"))
    token = am.create_session(ip="1.2.3.4", user_agent="UA", username="alice")
    assert am.get_session_username(token) == "alice"


def test_create_session_defaults_to_anonymous():
    am = AuthManager(password_hash=AuthManager.hash_password("p"))
    token = am.create_session()
    assert am.get_session_username(token) == "anonymous"


def test_get_session_username_unknown_token():
    am = AuthManager(password_hash=AuthManager.hash_password("p"))
    assert am.get_session_username("no-such-token") is None
