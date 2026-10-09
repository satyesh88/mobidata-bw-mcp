import pytest

from mobidata_bw_mcp.clients.wfs import validate_filter


def test_simple_cql_filter_is_allowed() -> None:
    assert validate_filter("form_factor = 'bicycle' AND current_range_meters > 1000")


@pytest.mark.parametrize(
    "value",
    ["name = 'x'; DROP TABLE things", "name = 'x' -- comment", "name = 'x' || chr(10)"],
)
def test_unsafe_cql_filter_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        validate_filter(value)