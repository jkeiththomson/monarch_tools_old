from monarch_tools.extractors.chase_legacy import _amount_to_value


def test_amount_positive():
    assert _amount_to_value("12.34") == 12.34
    assert _amount_to_value("$1,234.56") == 1234.56


def test_amount_parentheses_negative():
    assert _amount_to_value("(12.34)") == -12.34
    assert _amount_to_value("($1,234.56)") == -1234.56


def test_amount_minus_variants():
    assert _amount_to_value("-50.00") == -50.00
    assert _amount_to_value("50.00-") == -50.00


def test_amount_unicode_minus():
    assert _amount_to_value("−10.00") == -10.00


def test_amount_cr_forces_positive():
    assert _amount_to_value("10.00 CR") == 10.00
    assert _amount_to_value("(10.00) CR") == 10.00
    assert _amount_to_value("-10.00 CR") == 10.00


def test_amount_cents_only():
    assert _amount_to_value(".99") == 0.99
    assert _amount_to_value("$.99") == 0.99
