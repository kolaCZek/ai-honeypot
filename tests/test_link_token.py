from honeypot.link_token import sign, verify


SECRET = b"\x01" * 32


def test_sign_round_trip():
    t = sign("1.2.3.4", "/users", SECRET)
    assert isinstance(t, str) and len(t) == 16
    assert verify("1.2.3.4", "/users", t, SECRET)


def test_wrong_path():
    t = sign("1.2.3.4", "/users", SECRET)
    assert not verify("1.2.3.4", "/admin", t, SECRET)


def test_wrong_ip():
    t = sign("1.2.3.4", "/users", SECRET)
    assert not verify("5.6.7.8", "/users", t, SECRET)


def test_wrong_token():
    assert not verify("1.2.3.4", "/users", "deadbeef" * 2, SECRET)


def test_empty_token():
    assert not verify("1.2.3.4", "/users", "", SECRET)
