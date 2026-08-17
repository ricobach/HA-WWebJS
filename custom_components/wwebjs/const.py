"""Constants for the WWebJS integration."""

from datetime import timedelta

DOMAIN = "wwebjs"

CONF_BASE_URL = "base_url"
CONF_API_KEY = "api_key"
CONF_SESSION_ID = "session_id"
CONF_PHONE_NUMBER = "phone_number"

SUBENTRY_TYPE_SESSION = "session"

SERVICE_SEND_MESSAGE = "send_message"

ATTR_SESSION = "session"
ATTR_TARGET = "target"
ATTR_MESSAGE = "message"
ATTR_MEDIA = "media"
ATTR_IMAGE = "image"
ATTR_DELETE_AFTER = "delete_after"
ATTR_DELETE_IF_UNREAD_AFTER = "delete_if_unread_after"
ATTR_CLEANUP_KEY = "cleanup_key"
ATTR_DELETE_FOR_EVERYONE = "delete_for_everyone"

PLATFORMS = ["sensor"]

HEALTH_SCAN_INTERVAL = timedelta(seconds=60)
HEALTH_FAILURES_BEFORE_RESTART = 3
HEALTH_RESTART_COOLDOWN = timedelta(minutes=5)

LIFECYCLE_SCAN_INTERVAL = timedelta(seconds=30)
STORAGE_VERSION = 1
STORAGE_KEY = "wwebjs.message_lifecycle"
