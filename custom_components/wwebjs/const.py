"""Constants for the WWebJS integration."""

from datetime import timedelta

DOMAIN = "wwebjs"

CONF_BASE_URL = "base_url"
CONF_API_KEY = "api_key"
CONF_SESSION_ID = "session_id"
CONF_PHONE_NUMBER = "phone_number"

SUBENTRY_TYPE_SESSION = "session"

SERVICE_SEND_MESSAGE = "send_message"
SERVICE_SEND_LOCATION = "send_location"

ATTR_SESSION = "session"
ATTR_TARGET = "target"
ATTR_MESSAGE = "message"
ATTR_MEDIA = "media"
ATTR_IMAGE = "image"
ATTR_MEDIA_ENTITY = "media_entity"
ATTR_LOCATION_ENTITY = "location_entity"
ATTR_DESCRIPTION = "description"
ATTR_DELETE_AFTER = "delete_after"
ATTR_DELETE_IF_UNREAD_AFTER = "delete_if_unread_after"
ATTR_CLEANUP_KEY = "cleanup_key"
ATTR_DELETE_FOR_EVERYONE = "delete_for_everyone"

PLATFORMS = ["sensor", "button"]

HEALTH_SCAN_INTERVAL = timedelta(seconds=60)
HEALTH_FAILURES_BEFORE_RESTART = 3
HEALTH_RECOVERY_BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=30),
)
HEALTH_AUTH_FAILURE_STATES = {
    "AUTH_FAILURE",
    "UNPAIRED",
    "PAIRING",
    "QR_RECEIVED",
}
HEALTH_TRANSIENT_STATES = {
    "DISCONNECTED",
    "ERROR",
    "UNKNOWN",
    "UNLAUNCHED",
}

LIFECYCLE_SCAN_INTERVAL = timedelta(seconds=30)
STORAGE_VERSION = 1
STORAGE_KEY = "wwebjs.message_lifecycle"

HISTORY_STORAGE_VERSION = 1
HISTORY_STORAGE_KEY = "wwebjs.message_history"
HISTORY_LIMIT_PER_SESSION = 25
HISTORY_SENSOR_LIMIT = 10
