import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from dvsportal import DVSPortal
from dvsportal.exceptions import (
    DVSPortalAuthError,
    DVSPortalConnectionError,
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
