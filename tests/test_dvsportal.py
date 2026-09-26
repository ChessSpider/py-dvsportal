import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from dvsportal import DVSPortal
from dvsportal.const import API_BASE_URI, API_BASE_URI_PORTAL
from dvsportal.exceptions import (
    DVSPortalAuthError,
    DVSPortalConnectionError,
    DVSPortalError,
)


@pytest_asyncio.fixture
async def dvsportal():
    """Fixture to initialize a DVSPortal instance."""
    async with DVSPortal(
        api_host="api.dvsportal.test",
        identifier="test_user",
        password="test_password"
    ) as client:
        yield client


# --- Test _request method ---
@pytest.mark.asyncio
async def test_request_success(dvsportal : DVSPortal):
    """Test successful _request call."""
    with patch.object(dvsportal._session, "request", new=AsyncMock()) as mock_request:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json = AsyncMock(return_value={"key": "value"})
        mock_request.return_value = mock_response

        result = await dvsportal._request("/test-endpoint")
        assert result == {"key": "value"}


@pytest.mark.asyncio
async def test_request_timeout(dvsportal : DVSPortal):
    """Test _request timeout handling."""
    with patch.object(dvsportal._session, "request", side_effect=asyncio.TimeoutError):
        with pytest.raises(DVSPortalConnectionError):
            await dvsportal._request("/test-endpoint")


def mock_request_side_effect(uri: str, method: str = "POST", json=None, headers=None):
    # Return success on GET /login (fetch_default_type_id)
    if method == "GET" and uri == "login":
        return {
            "PermitMediaTypes":[{"ID":1,"Name":"Aanmeldcode kenteken"}],
            "LoginMethods":["Pas"],
            "DefaultLoginMethod":0,
            "ZipCodeMandatory":False,
            "FlowInfos":{}
        }
    # Return invalid credentials on POST /login
    if method == "POST" and uri == "login":
        return {"LoginStatus": 2, "ErrorMessage": "Invalid credentials"}
    # Fallback or other calls if needed
    return {"SomeKey": "SomeValue"}

@pytest.mark.asyncio
async def test_request_auth_error(dvsportal: DVSPortal):
    with patch.object(dvsportal, "_request", side_effect=mock_request_side_effect):
        with pytest.raises(DVSPortalAuthError):
            await dvsportal.token()


@pytest.mark.asyncio
async def test_token_success(dvsportal: DVSPortal):
    """Test successful token generation."""
    async def mock_request_side_effect(uri: str, method: str = "POST", json=None, headers=None):
        # 1) GET /login is needed for fetch_default_type_id:
        if method == "GET" and uri == "login":
            return {
                "PermitMediaTypes": [{"ID": 1}],
                "LoginMethods": ["Pas"],
                "DefaultLoginMethod": 0,
                "ZipCodeMandatory": False,
                "FlowInfos": {}
            }
        # 2) POST /login returns the token:
        if method == "POST" and uri == "login":
            return {"Token": "test_token"}
        return {}

    with patch.object(dvsportal, "_request", side_effect=mock_request_side_effect):
        token = await dvsportal.token()
        assert token == "test_token"


@pytest.mark.asyncio
async def test_fetch_default_type_id(dvsportal: DVSPortal):
    """Test fetching default type ID."""
    async def mock_request_side_effect(uri: str, method: str = "POST", json=None, headers=None):
        # Only call here is GET /login
        if method == "GET" and uri == "login":
            return {"PermitMediaTypes": [{"ID": 123}]}
        return {}

    with patch.object(dvsportal, "_request", side_effect=mock_request_side_effect):
        await dvsportal.fetch_default_type_id()
        assert dvsportal.default_type_id == 123

@pytest.mark.asyncio
async def test_update(dvsportal: DVSPortal):
    """Test the update method."""
    # Anonymized/trimmed example for "login/getbase":
    mock_getbase_response = {
        "Permits": [
            {
                "PermitMedias": [
                    {
                        "TypeID": 1,
                        "Code": "ABC",
                        "Balance": 100.0,
                        "ActiveReservations": [
                            {
                                "ReservationID": "res123",
                                "ValidFrom": "2025-01-01",
                                "ValidUntil": "2025-01-31",
                                "LicensePlate": {"Value": "ABC123"},
                                "Units": 1
                            }
                        ],
                        "LicensePlates": [
                            {"Value": "ABC123", "Name": "Car"}
                        ],
                        "History": {
                            "Reservations": {
                                "Items": [
                                    {
                                        "LicensePlate": {
                                            "Value": "DEF456",
                                            "DisplayValue": "DEF456"
                                        },
                                        "ReservationID": "res789",
                                        "ValidFrom": "2024-01-01",
                                        "ValidUntil": "2024-01-31",
                                        "Units": 1
                                    }
                                ]
                            }
                        }
                    }
                ],
                "UnitPrice": 50.0
            }
        ]
    }

    async def mock_request_side_effect(uri: str, method: str = "POST", json=None, headers=None):
        if method == "GET" and uri == "login":
            # fetch_default_type_id (so it doesn't fail)
            return {
                "PermitMediaTypes": [{"ID": 1}],
                "LoginMethods": ["Pas"],
                "DefaultLoginMethod": 0,
            }
        elif method == "POST" and uri == "login":
            # token
            return {"Token": "dummy_token"}
        elif method == "POST" and uri == "login/getbase":
            # the important "Permits" response for update
            return mock_getbase_response
        return {}

    with patch.object(dvsportal, "_request", side_effect=mock_request_side_effect):
        await dvsportal.update()

        # Now all your assertions will pass because the JSON has "Permits"
        assert dvsportal._default_type_id == 1
        assert dvsportal._default_code == "ABC"
        assert dvsportal._balance == 100.0
        assert dvsportal._unit_price == 50.0
        assert len(dvsportal._active_reservations) == 1
        assert len(dvsportal._historic_reservations) == 1



@pytest.mark.asyncio
async def test_create_reservation(dvsportal: DVSPortal):
    """Test creating a reservation."""
    async def mock_request_side_effect(uri: str, method: str = "POST", json=None, headers=None):
        # For create_reservation, we do token() first => GET/POST login
        if method == "GET" and uri == "login":
            return {"PermitMediaTypes": [{"ID": 1}]}
        if method == "POST" and uri == "login":
            return {"Token": "dummy_token"}
        # Then call POST /reservation/create => success
        if method == "POST" and uri == "reservation/create":
            return {"Success": True}
        return {}

    with patch.object(dvsportal, "_request", side_effect=mock_request_side_effect):
        result = await dvsportal.create_reservation(
            license_plate_value="ABC123",
            license_plate_name="Car",
            date_from=datetime.now()
        )
        assert result["Success"]


@pytest.mark.asyncio
async def test_end_reservation(dvsportal: DVSPortal):
    """Test ending a reservation."""
    async def mock_request_side_effect(uri: str, method: str = "POST", json=None, headers=None):
        # For end_reservation, token() is called => GET/POST login
        if method == "GET" and uri == "login":
            return {"PermitMediaTypes": [{"ID": 1}]}
        if method == "POST" and uri == "login":
            return {"Token": "dummy_token"}
        # Then call POST /reservation/end => success
        if method == "POST" and uri == "reservation/end":
            return {"Success": True}
        return {}

    with patch.object(dvsportal, "_request", side_effect=mock_request_side_effect):
        result = await dvsportal.end_reservation(reservation_id="res123")
        assert result["Success"]


@pytest.mark.asyncio
async def test_store_license_plate(dvsportal: DVSPortal):
    """Test storing a license plate."""
    async def mock_request_side_effect(uri: str, method: str = "POST", json=None, headers=None):
        # For store_license_plate, token() => GET/POST login
        if method == "GET" and uri == "login":
            return {"PermitMediaTypes": [{"ID": 1}]}
        if method == "POST" and uri == "login":
            return {"Token": "dummy_token"}
        # Then POST /permitmedialicenseplate/upsert => success
        if method == "POST" and uri == "permitmedialicenseplate/upsert":
            return {"Success": True}
        return {}

    with patch.object(dvsportal, "_request", side_effect=mock_request_side_effect):
        result = await dvsportal.store_license_plate(
            license_plate="ABC123",
            name="Car"
        )
        assert result["Success"]


@pytest.mark.asyncio
async def test_close_session(dvsportal: DVSPortal):
    """Test session cleanup."""
    with patch.object(dvsportal._session, "close", new=AsyncMock()) as mock_close:
        await dvsportal.close()
        mock_close.assert_called_once()


# --- /DVSPortal/api/ flavour ---

def _portal_login_get():
    """GET login as served by the /DVSPortal/api/ flavour."""
    return {
        "PermitMediaTypes": [{"ID": 4, "Name": "Bezoekersaccount"}],
        # Note: DefaultLoginMethod is an *index* into LoginMethods, so this
        # says "Pas" -- which is 2 in the enum, not 1.
        "LoginMethods": ["Gebruiker", "Pas", "ResetCode"],
        "DefaultLoginMethod": 1,
    }


def _portal_request(dvsportal, captured=None, getbase=None, history_pages=None):
    """Build a _request side effect that only answers on the portal base."""
    async def side_effect(uri: str, method: str = "POST", json=None, headers=None):
        if method == "GET" and uri == "login":
            if dvsportal._api_base_uri == API_BASE_URI:
                # The legacy path is swallowed by the municipality's new SPA,
                # which answers 200 with HTML rather than 404.
                raise DVSPortalError(200, {"message": "<!DOCTYPE html>"})
            return _portal_login_get()
        if method == "POST" and uri == "login":
            if captured is not None:
                captured.update(json or {})
            # No Token: this flavour authenticates with a session cookie.
            return getbase if getbase is not None else {"Name": "Tester"}
        if method == "POST" and uri == "login/getbase":
            return getbase
        if method == "POST" and uri == "history/reservations":
            return (history_pages or {}).get((json or {}).get("page"), {"Items": []})
        return {}
    return side_effect


@pytest.mark.asyncio
async def test_detects_portal_api_base(dvsportal: DVSPortal):
    """Falls through to /DVSPortal/api/ when the legacy base serves HTML."""
    with patch.object(dvsportal, "_request", side_effect=_portal_request(dvsportal)):
        await dvsportal.fetch_default_type_id()

    assert dvsportal._api_base_uri == API_BASE_URI_PORTAL
    assert dvsportal.uses_portal_api is True
    assert dvsportal.default_type_id == 4


@pytest.mark.asyncio
async def test_portal_login_uses_numeric_method_and_needs_no_token(dvsportal: DVSPortal):
    """Login sends the enum value and survives a response without a Token."""
    captured: dict = {}
    with patch.object(dvsportal, "_request",
                      side_effect=_portal_request(dvsportal, captured=captured)):
        token = await dvsportal.token()

    assert token is None
    assert dvsportal._authenticated is True
    # "Pas" is 2. Sending DefaultLoginMethod (1) would log in as "Gebruiker"
    # and fail with a misleading "username or password is incorrect".
    assert captured["loginMethod"] == 2
    assert captured["identifier"] == "test_user"
    # The model rejects the body outright when these are absent.
    for key in ("otp", "resetCode", "asIdentifier", "zipCode"):
        assert key in captured


@pytest.mark.asyncio
async def test_portal_update_reads_history_from_endpoint(dvsportal: DVSPortal):
    """History comes from history/reservations when HasHistory is set."""
    getbase = {
        "Name": "Tester",
        "Permits": [{
            "UnitPrice": 0.5,
            "PermitMedias": [{
                "TypeID": 4,
                "Code": "20727",
                "Balance": 8382,
                "HasHistory": True,
                "ActiveReservations": [],
                "LicensePlates": [{"Value": "AA11BB", "Name": "Car"}],
            }],
        }],
    }
    history_pages = {
        1: {"Page": 1, "TotalPages": 2, "TotalItems": 3, "Items": [
            {"ReservationID": 1, "ValidFrom": "2026-09-08T17:44:00Z",
             "ValidUntil": "2026-09-08T19:18:00Z", "Units": 95,
             "LicensePlate": {"Value": "CC22DD", "DisplayValue": "CC22DD",
                              "Name": "", "IsAnonymised": False}},
        ]},
        2: {"Page": 2, "TotalPages": 2, "TotalItems": 3, "Items": [
            {"ReservationID": 2, "ValidFrom": "2026-09-07T10:00:00Z",
             "ValidUntil": "2026-09-07T11:00:00Z", "Units": 60,
             "LicensePlate": {"Value": "EE33FF", "DisplayValue": "EE33FF",
                              "Name": "", "IsAnonymised": False}},
            {"ReservationID": 3, "ValidFrom": "2026-09-06T10:00:00Z",
             "ValidUntil": "2026-09-06T11:00:00Z", "Units": 60,
             "LicensePlate": {"Value": "", "DisplayValue": "********",
                              "Name": "", "IsAnonymised": True}},
        ]},
    }

    with patch.object(dvsportal, "_request",
                      side_effect=_portal_request(dvsportal, getbase=getbase,
                                                  history_pages=history_pages)):
        await dvsportal.update()

    assert dvsportal.balance == 8382
    assert dvsportal.default_code == "20727"
    # Both pages walked, the anonymised row dropped.
    assert sorted(dvsportal.historic_reservations) == ["CC22DD", "EE33FF"]
    assert "AA11BB" in dvsportal.known_license_plates
