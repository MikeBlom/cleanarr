from app.auth.password import hash_password, verify_password


def test_hash_password_returns_hash():
    h = hash_password("mypassword")
    assert h != "mypassword"
    assert len(h) > 20


def test_verify_password_correct():
    h = hash_password("secret123")
    assert verify_password("secret123", h) is True


def test_verify_password_incorrect():
    h = hash_password("secret123")
    assert verify_password("wrong", h) is False


def test_hash_password_unique_salts():
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2
