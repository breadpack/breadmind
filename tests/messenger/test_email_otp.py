from breadmind.messenger.auth.email_otp import generate_code, hash_code


def test_generate_code_is_6_digits():
    code = generate_code()
    assert len(code) == 6
    assert code.isdigit()


def test_hash_code_deterministic():
    h1 = hash_code("123456", "alice@x.com")
    h2 = hash_code("123456", "alice@x.com")
    assert h1 == h2


def test_hash_code_salt_by_email():
    h1 = hash_code("123456", "a@x.com")
    h2 = hash_code("123456", "b@x.com")
    assert h1 != h2
