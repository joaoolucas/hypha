from hypha.utils import bar, clean_address, fmt_price, fmt_usd, is_ton_address, to_friendly, to_raw


def test_fmt_price():
    assert fmt_price(None) == "—"
    assert fmt_price(0) == "$0"
    assert fmt_price(1.2345) == "$1.23"
    assert fmt_price(0.0123) == "$0.0123"
    # tiny price -> subscript-zero notation: 0.000142 == $0.0₂142
    assert fmt_price(0.000142) == "$0.0₂142"
    assert fmt_price(0.0000142) == "$0.0₃142"


def test_clean_address_friendly():
    a = "EQCcLAW537KnRg_aSPrnQJoyYjOZkzqYp6FVmRUvN1crSazV"
    assert clean_address(f"check this {a} please") == a
    assert is_ton_address(a)


def test_clean_address_raw():
    a = "0:" + "a" * 64
    assert clean_address(a) == a


def test_clean_address_rejects_garbage():
    assert clean_address("not an address") is None
    assert clean_address("0xdeadbeef") is None


def test_fmt_usd():
    assert fmt_usd(None) == "—"
    assert fmt_usd(1_500_000) == "$1.50M"
    assert fmt_usd(2500) == "$2.5k"
    assert fmt_usd(42) == "$42"


def test_bar_bounds():
    assert bar(0) == "░" * 10
    assert bar(100) == "▓" * 10
    assert len(bar(57)) == 10


def test_to_raw_roundtrips_to_friendly():
    raw = "0:" + "ab" * 32
    # to_friendly(raw) is a UQ…/EQ… address; to_raw must invert it back exactly.
    assert to_raw(to_friendly(raw)) == raw
    assert to_raw(to_friendly(raw, bounceable=True)) == raw


def test_to_raw_passthrough_and_garbage():
    raw = "0:" + "cd" * 32
    assert to_raw(raw) == raw            # already raw -> unchanged
    assert to_raw("") == ""
    assert to_raw("not-base64!!") == "not-base64!!"


def test_to_raw_matches_known_friendly():
    a = "EQCcLAW537KnRg_aSPrnQJoyYjOZkzqYp6FVmRUvN1crSazV"
    raw = to_raw(a)
    assert raw.startswith("0:") and len(raw) == 66   # workchain 0 + 64 hex chars
