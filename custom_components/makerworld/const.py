"""Constants for the MakerWorld integration."""

DOMAIN = "makerworld"

CONF_USER = "user"
CONF_COOKIE = "cookie"
CONF_USER_AGENT = "user_agent"
CONF_MAX_MODELS = "max_models"

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_MAX_MODELS = 0
DEFAULT_SCAN_INTERVAL = 3600

PLATFORMS = ["sensor", "binary_sensor", "button"]
