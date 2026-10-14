import pytest

from mobidata_bw_mcp.tools.signs import normalized_code, sign_unit, sign_value


@pytest.mark.parametrize(
    ("raw_code", "code", "value", "unit"),
    [
        ("DE:277", "277", None, None),
        ("DE:262[7.5]", "262", 7.5, "t"),
        ("DE:263-11,5", "263", 11.5, "t"),
        ("DE:264[2.2]", "264", 2.2, "m"),
        ("DE:265-3,8", "265", 3.8, "m"),
        ("DE:266[12]", "266", 12.0, "m"),
    ],
)
def test_truck_sign_code_value_and_unit(raw_code, code, value, unit) -> None:
    assert normalized_code(raw_code) == code
    assert sign_value(raw_code) == value
    assert sign_unit(raw_code) == unit