"""Asynchronous Python client for the DVSPortal API."""
import asyncio
import base64
import socket
import warnings
from asyncio import exceptions as async_exceptions
from datetime import datetime
from typing import TypedDict

import aiohttp
import async_timeout
from yarl import URL

from .__version__ import __version__
from .const import (
    API_BASE_URI,
    API_BASE_URIS,
    DEFAULT_LOGIN_METHOD,
    HISTORY_MAX_PAGES,
    LOGIN_METHOD_NUMERIC,
    XSRF_COOKIE_NAME,
    XSRF_HEADER_NAME,
)
from .exceptions import (
    DVSPortalAuthError,
    DVSPortalConnectionError,
    DVSPortalError,
)

# --- TypedDict Definitions ---

class LicensePlate(TypedDict):
    Value: str
    Name: str


class UpstreamReservation(TypedDict):
    ReservationID: str
    ValidFrom: datetime
    ValidUntil: datetime
    LicensePlate: LicensePlate
    Units: int


class Reservation(TypedDict):
    reservation_id: str
    valid_from: datetime
    valid_until: datetime
    license_plate: str
    units: int
    cost: float | None


class PermitMedia(TypedDict):
    TypeID: int
    Code: str
    Balance: float
    RemainingUpgrades: int
    RemainingDowngrades: int
    ActiveReservations: list[UpstreamReservation]
    LicensePlates: list[LicensePlate]
    # /DVSWebAPI/ embeds the history here; /DVSPortal/ sets HasHistory instead
    # and serves it from history/reservations.
    History: dict
    HasHistory: bool


class Permit(TypedDict):
    PermitMedias: list[PermitMedia]
    UnitPrice: float


class HistoricReservation(TypedDict):
    ReservationID: str
    ValidFrom: datetime
    ValidUntil: datetime
    Units: int



def _is_anonymised(license_plate: dict) -> bool:
    """Whether the portal has redacted this plate.

    /DVSWebAPI/ only masks the display value; /DVSPortal/ says so outright.
    """
    if license_plate.get("IsAnonymised"):
        return True
    return license_plate.get("DisplayValue") == "********"


# --- DVSPortal Class ---

class DVSPortal:
    """Main class for handling connections with DVSPortal."""

    def __init__(
        self,
        api_host: str,
        identifier: str,
        password: str,
        loop=None,
        request_timeout: int = 10,
        session=None,
        user_agent: str | None = None,
        api_base_uri: str | None = None,
    ):
        """Initialize connection with DVSPortal.

        ``api_base_uri`` pins the API flavour (see const.API_BASE_URIS). Leave
        it at None to probe the host on first use.
        """
        self._loop = loop
        self._session = session
        self._close_session = False

        self.api_host = api_host
        self._api_base_uri = api_base_uri
        self._identifier = identifier
        self._password = password

        self.request_timeout = request_timeout
        self.user_agent = user_agent

        self._token: str | None = None
        self._authenticated = False

        if self._loop is None:
            self._loop = asyncio.get_event_loop()

        if self._session is None:
            self._session = aiohttp.ClientSession()
            self._close_session = True

        if self.user_agent is None:
            self.user_agent = f"PythonDVSPortal/{__version__}"

        self._balance: float | None = None
        self._unit_price: float | None = None
        self._active_reservations: dict[str, Reservation]= {}
        self._known_license_plates: dict[str, str] = {}
        self._default_type_id: int | None = None
        self._default_code: str | None = None
        self._historic_reservations: dict[str, HistoricReservation] = {}

    @property
    def balance(self) -> float | None:
        return self._balance

    @property
    def unit_price(self) -> float | None:
        return self._unit_price

    @property
    def active_reservations(self) -> dict[str, Reservation]:
        return self._active_reservations

    @property
    def known_license_plates(self) -> dict[str, str]:
        return self._known_license_plates

    @property
    def default_type_id(self) -> int | None:
        return self._default_type_id

    @property
    def default_code(self) -> str | None:
        return self._default_code

    @property
    def historic_reservations(self) -> dict[str, HistoricReservation]:
        return self._historic_reservations

    async def _request(self, uri: str, method: str = "POST", json=None, headers=None):
        """Handle a request to DVSPortal."""
        json = json or {}
        headers = headers or {}
        url = URL.build(
            scheme="https", host=self.api_host, port=443,
            path=self._api_base_uri or API_BASE_URI
        ).join(URL(uri))

        default_headers = {
            "User-Agent": self.user_agent,
        }

        # The /DVSPortal/api/ flavour guards everything past the login call
        # with an antiforgery token handed out as a cookie; without the header
        # those endpoints answer 401. Harmless on hosts that do not set it.
        xsrf = self._xsrf_token()
        if xsrf is not None:
            default_headers[XSRF_HEADER_NAME] = xsrf

        try:
            async with async_timeout.timeout(self.request_timeout):
                response = await self._session.request(
                    method, url, json=json, headers={**default_headers, **headers}, ssl=True
                )
        except async_exceptions.TimeoutError as exception:
            raise DVSPortalConnectionError(
                "Timeout occurred while connecting to DVSPortal API."
            ) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            raise DVSPortalConnectionError(
                "Error occurred while communicating with DVSPortal."
            ) from exception

        content_type = response.headers.get("Content-Type", "")

        if not content_type.startswith("application/json"):
            response_text = await response.text()
            raise DVSPortalError(
                response.status, {"message": response_text}
            )

        response_json = await response.json()
        if (response.status // 100) in [4, 5] or "ErrorMessage" in response_json:
            raise DVSPortalError(
                response.status, response_json
            )

        return response_json

    def _xsrf_token(self) -> str | None:
        """Return the antiforgery cookie value, if the host handed one out."""
        jar = getattr(self._session, "cookie_jar", None)
        if jar is None:
            return None
        for cookie in jar:
            if cookie.key == XSRF_COOKIE_NAME:
                return cookie.value
        return None

    @property
    def uses_portal_api(self) -> bool:
        """True when this host speaks the cookie-authenticated flavour."""
        return self._api_base_uri == API_BASE_URIS[1]

    async def _detect_api_base_uri(self) -> dict:
        """Probe which API flavour this host speaks, and return GET login.

        Hosts that have moved on from /DVSWebAPI/ do not 404 that path: it is
        swallowed by the municipality's new single-page app, which answers 200
        with an HTML document. So probe on the content type, not the status.
        """
        errors = []
        for base_uri in API_BASE_URIS:
            self._api_base_uri = base_uri
            try:
                response = await self._request("login", method="GET")
            except DVSPortalError as err:
                errors.append(f"{base_uri}: {err}")
                continue
            if "PermitMediaTypes" in response:
                return response
            errors.append(f"{base_uri}: no PermitMediaTypes in response")

        self._api_base_uri = None
        raise DVSPortalError(
            f"Could not determine the API flavour of {self.api_host}. "
            f"Tried: {'; '.join(errors)}"
        )

    async def fetch_default_type_id(self) -> None:
        """Fetches the default permit media type ID."""
        try:
            if self._api_base_uri is None:
                response = await self._detect_api_base_uri()
            else:
                response = await self._request("login", method="GET")
            self._default_type_id = response["PermitMediaTypes"][0]["ID"]
        except KeyError as e:
            raise DVSPortalError("Failed to fetch default type ID: Missing key in response") from e

    async def token(self) -> str | None:
        """Log in if needed and return the token, if this host issues one.

        The /DVSPortal/api/ flavour does not: it authenticates the session
        with a cookie and returns the ``login/getbase`` payload straight from
        the login call, so None here does not mean "not logged in" -- check
        ``self._authenticated`` for that.
        """
        if self._authenticated:
            return self._token

        if self._default_type_id is None:
            await self.fetch_default_type_id()

        payload: dict = {
            "identifier": self._identifier,
            "password": self._password,
            "permitMediaTypeID": self._default_type_id,
        }
        if self.uses_portal_api:
            payload["loginMethod"] = LOGIN_METHOD_NUMERIC[DEFAULT_LOGIN_METHOD]
            # The portal sends these explicitly; the model rejects the body
            # outright when they are missing.
            payload.update(
                otp=None, resetCode=None, asIdentifier=None, zipCode=None
            )
        else:
            payload["loginMethod"] = DEFAULT_LOGIN_METHOD

        response = await self._request("login", json=payload)

        if response.get("LoginStatus") == 2:
            raise DVSPortalAuthError(
                f"Authentication failed: {response.get('ErrorMessage', 'Unknown authentication error')}"
            )

        self._token = response.get("Token")
        if self._token is None and not self.uses_portal_api:
            raise DVSPortalError("Login succeeded but no token was returned")

        self._authenticated = True
        return self._token

    async def authorization_header(self) -> dict[str, str]:
        await self.token()
        if self._token is None:
            # Cookie-authenticated host: the session carries the login.
            return {}
        return {
            "Authorization": "Token " + str(base64.b64encode(str(self._token).encode("utf-8")), "utf-8")
        }

    async def _history_items(self, permit_media: PermitMedia) -> list[dict]:
        """Return the permit media's historic reservations.

        /DVSWebAPI/ embeds them in login/getbase. /DVSPortal/ replaces that
        with a ``HasHistory`` flag and a paginated endpoint.
        """
        history = permit_media.get("History")
        if history:
            return history.get("Reservations", {}).get("Items", [])

        if not permit_media.get("HasHistory"):
            return []

        items: list[dict] = []
        page = 1
        while page <= HISTORY_MAX_PAGES:
            response = await self._request(
                "history/reservations",
                json={
                    "permitMediaTypeID": permit_media["TypeID"],
                    "permitMediaCode": permit_media["Code"],
                    "page": page,
                },
            )
            items.extend(response.get("Items", []))
            if page >= response.get("TotalPages", page):
                break
            page += 1

        return items

    async def update(self) -> None:
        """Fetch data from DVSPortal."""
        await self.token()

        authorization_header = await self.authorization_header()
        response = await self._request(
            "login/getbase",
            headers=authorization_header
        )

        if not response.get("Permits"):
            raise DVSPortalError("No zonal code found")
        if len(response["Permits"]) > 1:
            raise DVSPortalError("More than one zonal code found")

        permit_media: PermitMedia = response["Permits"][0]["PermitMedias"][0]

        self._default_type_id = permit_media["TypeID"]
        self._default_code = permit_media["Code"]

        self._balance = permit_media["Balance"]
        self._unit_price = response["Permits"][0]["UnitPrice"]

        # Map Active Reservations from UpstreamReservation to Reservation
        self._active_reservations = {
            reservation["LicensePlate"]["Value"]: {
                "reservation_id": reservation["ReservationID"],
                "valid_from": reservation["ValidFrom"],
                "valid_until": reservation["ValidUntil"],
                "license_plate": reservation["LicensePlate"]["Value"],
                "units": reservation["Units"],
                "cost": reservation["Units"] * self._unit_price
                if self._unit_price else None,
            }
            for reservation in permit_media.get("ActiveReservations", [])
        }


        history_items = await self._history_items(permit_media)

        # Map Historic Reservations
        self._historic_reservations = {
            item["LicensePlate"]["Value"]: {
                "ReservationID": item["ReservationID"],
                "ValidFrom": item["ValidFrom"],
                "ValidUntil": item["ValidUntil"],
                "Units": item["Units"],
            }
            for item in history_items
            if not _is_anonymised(item["LicensePlate"])
        }

        # Known License Plates
        history_license_plates = {
            item["LicensePlate"]["DisplayValue"]: ""
            for item in history_items
            if not _is_anonymised(item["LicensePlate"])
        }

        active_license_plates = {
            reservation["LicensePlate"]["Value"]: ""
            for reservation in permit_media["ActiveReservations"]
        }

        named_license_plates = {
            plate["Value"]: plate["Name"]
            for plate in permit_media["LicensePlates"]
        }

        self._known_license_plates = {
            **history_license_plates,
            **active_license_plates,
            **named_license_plates
        }


    async def end_reservation(
        self,
        *,
        reservation_id: str,
        type_id: int | None = None,
        code: str | None = None
    ) -> dict:
        """End a reservation."""
        if type_id is None:
            type_id = self.default_type_id
        if code is None:
            code = self.default_code

        authorization_header = await self.authorization_header()

        return await self._request(
            "reservation/end",
            headers=authorization_header,
            json={
                "ReservationID": reservation_id,
                "permitMediaTypeID": type_id,
                "permitMediaCode": code
            }
        )

    async def create_reservation(
        self,
        license_plate_value: str | None = None,
        license_plate_name: str | None = None,
        type_id: int | None = None,
        code: str | None = None,
        date_from: datetime | None = None,
        date_until: datetime | None = None
    ) -> dict:
        """Create a reservation."""
        if type_id is None:
            type_id = self.default_type_id
        if code is None:
            code = self.default_code
        if date_from is None:
            date_from = datetime.now()

        request_data = {
            "DateFrom": date_from.isoformat(),
            "LicensePlate": {
                "Value": license_plate_value,
                "Name": license_plate_name
            },
            "permitMediaTypeID": type_id,
            "permitMediaCode": code
        }

        if date_until:
            request_data["DateUntil"] = date_until.isoformat()

        authorization_header = await self.authorization_header()

        return await self._request(
            "reservation/create",
            headers=authorization_header,
            json=request_data
        )

    async def store_license_plate(
        self,
        license_plate: str,
        name: str,
        permit_media_code: str | None = None
    ) -> dict:
        """Store a license plate."""
        authorization_header = await self.authorization_header()
        permit_media_code = permit_media_code or self.default_code

        payload = {
            "permitMediaTypeID": self.default_type_id,
            "permitMediaCode": permit_media_code,
            "licensePlate": {
                "Value": license_plate,
                "Name": name
            },
            "updateLicensePlate": None
        }

        return await self._request(
            "permitmedialicenseplate/upsert",
            headers=authorization_header,
            json=payload
        )

    async def close(self) -> None:
        """Close open client session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self) -> "DVSPortal":
        """Async enter."""
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        try:
            if self._session and not self._session.closed:
                await self._session.close()
        except Exception as e:
            warnings.warn(f"Failed to close session in __aexit__: {e}", stacklevel=2)

    def __del__(self):
        """Ensure session is closed when object is garbage-collected."""
        if self._session and not self._session.closed:
            warnings.warn(
                "DVSPortal instance was not properly closed. Call `await close()` or use `async with DVSPortal()`.", stacklevel=2
            )
            del self._session
