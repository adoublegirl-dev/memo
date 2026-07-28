from scripts.wait_for_services import fetch_json


def test_fetch_json_returns_none_for_unreachable_endpoint():
    assert fetch_json("http://127.0.0.1:1/not-running", timeout=0.1) is None
