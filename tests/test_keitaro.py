import httpx
import pytest
from fastapi.testclient import TestClient

from adrobot.keitaro import KeitaroClient, KeitaroError
from adrobot.main import create_app


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
def test_only_get_retries_a_failed_connection(method):
    calls = []

    def tracker(request):
        calls.append(request.method)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("timeout", request=request)
        return httpx.Response(200)

    with httpx.Client(
        base_url="https://tracker.test", transport=httpx.MockTransport(tracker)
    ) as http:
        client = KeitaroClient(http)
        if method == "GET":
            assert client.request(method, "campaigns").status_code == 200
            assert calls == ["GET", "GET"]
        else:
            with pytest.raises(KeitaroError):
                client.request(method, "campaigns")
            assert calls == [method]


def test_shared_client_lifetime(monkeypatch):
    monkeypatch.setenv("KEITARO_URL", "https://tracker.example")
    monkeypatch.setenv("KEITARO_API_KEY", "test")
    app = create_app()
    with TestClient(app):
        http = app.state.keitaro_client.http
        assert not http.is_closed
    assert http.is_closed
