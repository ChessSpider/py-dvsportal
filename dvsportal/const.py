"""DVSPortal constants."""

# Municipalities run one of two API flavours behind the same product.
#
# - /DVSWebAPI/api/ is the original one (e.g. Enschede). Login returns a
#   ``Token`` which is sent back as an ``Authorization`` header, and the
#   permit-media history is embedded in the ``login/getbase`` response.
# - /DVSPortal/api/ is the one used by, among others, Delft and Hoorn. It
#   authenticates with a session cookie instead of a token, and serves the
#   history from a separate paginated endpoint.
#
# The flavour is detected at runtime; see DVSPortal._detect_api_base_uri.
API_BASE_URI = "/DVSWebAPI/api/"
API_BASE_URI_PORTAL = "/DVSPortal/api/"
API_BASE_URIS = (API_BASE_URI, API_BASE_URI_PORTAL)

# The /DVSPortal/api/ flavour rejects the login method as a string and wants
# the numeric enum value instead.
#
# Careful: ``DefaultLoginMethod`` in the ``GET login`` response is an *index*
# into the ``LoginMethods`` array, NOT a value of this enum. For a host whose
# LoginMethods are ["Gebruiker", "Pas", "ResetCode"], DefaultLoginMethod == 1
# means "Pas" -- which is 2 here. Sending 1 instead logs in as "Gebruiker" and
# fails with a perfectly truthful "username or password is incorrect".
LOGIN_METHOD_NUMERIC = {
    "CallCenter": 0,
    "Gebruiker": 1,
    "Pas": 2,
    "ResetCode": 3,
    "SingleSignOn": 4,
    "UserAs": 5,
}
DEFAULT_LOGIN_METHOD = "Pas"

# The /DVSPortal/api/ flavour protects non-login endpoints with an antiforgery
# token: the value of this cookie has to be echoed back in this header.
XSRF_COOKIE_NAME = "Xsrf-DVSPortal"
XSRF_HEADER_NAME = "X-XSRF-TOKEN"

# History is paginated (10 items per page). Cap how much we walk so a permit
# with years of reservations cannot stall an update indefinitely.
HISTORY_MAX_PAGES = 5
