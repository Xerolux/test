import logging
from homeassistant.core import HomeAssistant, callback
import aiohttp
import async_timeout
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import aiohttp_client
from datetime import datetime, timedelta
import asyncio
import re
from .const import (
    DOMAIN,
    CONF_API_URL,
    CONF_POLLING_INTERVAL,
    CONF_USE_SSL,
    CONF_DEVICE_NAME,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_DEVICE_ID,
    CONF_MQTT_ENABLED,
    CONF_MQTT_BROKER,
    CONF_MQTT_PORT,
    CONF_MQTT_USERNAME,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_BASE_TOPIC,
    DEFAULT_POLLING_INTERVAL,
    DEFAULT_USE_SSL,
    DEFAULT_MQTT_PORT,
    DEFAULT_MQTT_ENABLED,
    API_READINGS,
)

# Timeout limits as constants
MIN_TIMEOUT_DURATION = 5
MAX_TIMEOUT_DURATION = 60
CACHE_DURATION = 30  # Cache API results for 30 seconds

_LOGGER = logging.getLogger(__name__)

# Validate firmware version format
def is_valid_firmware(firmware_version):
    """Validate firmware version format (e.g., 1.1.4)."""
    return bool(re.match(r'^[1-9]\d*\.\d+\.\d+$', firmware_version))

async def fetch_api_data(session, api_url, auth, use_ssl, timeout_duration, retry_attempts, cache):
    """Fetch data from the API with retry logic, caching, and timeout."""
    # Check if cached data is still valid
    if "timestamp" in cache and (cache["timestamp"] + timedelta(seconds=CACHE_DURATION)) > datetime.utcnow():
        _LOGGER.debug("Returning cached data")
        return cache["data"]

    for attempt in range(retry_attempts):
        try:
            async with async_timeout.timeout(timeout_duration):
                _LOGGER.debug(
                    "Attempting connection to API at %s (SSL=%s)",
                    api_url,
                    use_ssl,
                )
                async with session.get(api_url, auth=auth, ssl=use_ssl) as response:
                    response.raise_for_status()
                    data = await response.json()
                    _LOGGER.debug("API response received: %s", data)
                    
                    # Cache the data
                    cache["data"] = data
                    cache["timestamp"] = datetime.utcnow()
                    
                    return data
        except aiohttp.ClientConnectionError as err:
            _LOGGER.error("Connection error to API at %s: %s", api_url, err)
            if attempt + 1 == retry_attempts:
                raise ValueError("Connection error after multiple attempts.")
        except aiohttp.ClientResponseError as err:
            _LOGGER.error(
                "Invalid API response (Status code: %s, Message: %s)", err.status, err.message
            )
            raise ValueError("Invalid API response.")
        except asyncio.TimeoutError:
            _LOGGER.error("API request timed out at %s", api_url)
            raise ValueError("API request timed out.")
        except Exception as err:
            _LOGGER.error("Unexpected exception occurred: %s", err)
            raise ValueError("Unexpected error occurred.")

class VioletDeviceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Violet Pool Controller."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial user input step."""
        errors = {}

        if user_input is not None:
            base_ip = user_input[CONF_API_URL]  # Only the IP address is entered
            use_ssl = user_input.get(CONF_USE_SSL, DEFAULT_USE_SSL)
            protocol = "https" if use_ssl else "http"

            # Dynamically construct the full API URL
            api_url = f"{protocol}://{base_ip}{API_READINGS}"
            _LOGGER.debug("Constructed API URL: %s", api_url)

            device_name = user_input.get(CONF_DEVICE_NAME, "Violet Pool Controller")
            username = user_input.get(CONF_USERNAME)
            password = user_input.get(CONF_PASSWORD)
            device_id = user_input.get(CONF_DEVICE_ID, 1)

            # Mask sensitive info in logs
            masked_username = username[:1] + '*' * (len(username) - 2) + username[-1:]
            masked_password = '*' * len(password)
            _LOGGER.debug(f"Username: {masked_username}, Password: {masked_password}")

            await self.async_set_unique_id(base_ip)  # Use the base IP as the unique ID
            self._abort_if_unique_id_configured()

            session = aiohttp_client.async_get_clientsession(self.hass)

            # Adjust timeout duration dynamically
            timeout_duration = user_input.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL)
            timeout_duration = max(MIN_TIMEOUT_DURATION, min(timeout_duration, MAX_TIMEOUT_DURATION))

            retry_attempts = 3  # Retry attempts for connection errors
            auth = aiohttp.BasicAuth(username, password)

            try:
                cache = {}  # Initialize cache for API results
                # Fetch the API data
                data = await fetch_api_data(session, api_url, auth, use_ssl, timeout_duration, retry_attempts, cache)
                
                # Process the firmware version and validate
                await self._process_firmware_data(data, errors)

            except ValueError as err:
                _LOGGER.error("%s", err)
                errors["base"] = "api_error"  # Display a friendly error message in the form

            if not errors:
                # Only store the base IP address to avoid saving unnecessary data
                user_input[CONF_API_URL] = base_ip
                user_input[CONF_DEVICE_NAME] = device_name
                user_input[CONF_USERNAME] = username
                user_input[CONF_PASSWORD] = password
                user_input[CONF_DEVICE_ID] = device_id

                # Configuration success
                return self.async_create_entry(
                    title=f"{device_name} (ID {device_id})", data=user_input
                )

        # Display the form to the user with error handling and MQTT options
        data_schema = vol.Schema({
            vol.Required(CONF_API_URL): str,  # Only the IP address is entered
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional(CONF_POLLING_INTERVAL, default=DEFAULT_POLLING_INTERVAL): vol.All(vol.Coerce(int), vol.Range(min=5, max=3600)),
            vol.Optional(CONF_USE_SSL, default=DEFAULT_USE_SSL): bool,
            vol.Optional(CONF_DEVICE_NAME, default="Violet Pool Controller"): str,
            vol.Required(CONF_DEVICE_ID, default=1): vol.All(vol.Coerce(int), vol.Range(min=1)),
            vol.Optional(CONF_MQTT_ENABLED, default=DEFAULT_MQTT_ENABLED): bool,
            vol.Optional(CONF_MQTT_BROKER, default=""): str,
            vol.Optional(CONF_MQTT_PORT, default=DEFAULT_MQTT_PORT): vol.Coerce(int),
            vol.Optional(CONF_MQTT_USERNAME, default=""): str,
            vol.Optional(CONF_MQTT_PASSWORD, default=""): str,
            vol.Optional(CONF_MQTT_BASE_TOPIC, default="violet_pool_controller"): str,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def _process_firmware_data(self, data, errors):
        """Process and validate the firmware data."""
        firmware_version = data.get('fw') or data.get('SW_VERSION')

        # Additional carrier information extraction
        sw_version_carrier = data.get('SW_VERSION_CARRIER')
        hw_version_carrier = data.get('HW_VERSION_CARRIER')
        hw_serial_carrier = data.get('HW_SERIAL_CARRIER')

        if not firmware_version:
            _LOGGER.error("Firmware version not found in API response: %s", data)
            errors["base"] = "firmware_not_found"
            raise ValueError("Firmware version not found.")
        else:
            # Optional firmware format validation
            if is_valid_firmware(firmware_version):
                _LOGGER.info("Successfully read firmware version: %s", firmware_version)
            else:
                _LOGGER.error("Invalid firmware version received: %s", firmware_version)
                errors["base"] = "invalid_firmware"

        # Log additional carrier information
        _LOGGER.info("Carrier Software Version (SW_VERSION_CARRIER): %s", sw_version_carrier or "Not available")
        _LOGGER.info("Carrier Hardware Version (HW_VERSION_CARRIER): %s", hw_version_carrier or "Not available")
        _LOGGER.info("Carrier Hardware Serial (HW_SERIAL_CARRIER): %s", hw_serial_carrier or "Not available")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for the Violet device."""
        return VioletOptionsFlow(config_entry)

class VioletOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Violet Device."""

    def __init__(self, config_entry):
        """Initialize the options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options for the custom component."""
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Handle options for the Violet device."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options_schema = vol.Schema({
            vol.Optional(
                CONF_USERNAME,
                default=self.config_entry.data.get(CONF_USERNAME, "")
            ): str,
            vol.Optional(
                CONF_PASSWORD,
                default=self.config_entry.data.get(CONF_PASSWORD, "")
            ): str,
            vol.Optional(
                CONF_POLLING_INTERVAL,
                default=self.config_entry.data.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL)
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=3600)),
            vol.Optional(
                CONF_USE_SSL,
                default=self.config_entry.data.get(CONF_USE_SSL, DEFAULT_USE_SSL)
            ): bool,
            vol.Optional(
                CONF_MQTT_ENABLED,
                default=self.config_entry.data.get(CONF_MQTT_ENABLED, DEFAULT_MQTT_ENABLED)
            ): bool,
            vol.Optional(
                CONF_MQTT_BROKER,
                default=self.config_entry.data.get(CONF_MQTT_BROKER, "")
            ): str,
            vol.Optional(
                CONF_MQTT_PORT,
                default=self.config_entry.data.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT)
            ): vol.Coerce(int),
            vol.Optional(
                CONF_MQTT_USERNAME,
                default=self.config_entry.data.get(CONF_MQTT_USERNAME, "")
            ): str,
            vol.Optional(
                CONF_MQTT_PASSWORD,
                default=self.config_entry.data.get(CONF_MQTT_PASSWORD, "")
            ): str,
            vol.Optional(
                CONF_MQTT_BASE_TOPIC,
                default="violet_pool_controller"
            ): str,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=options_schema
        )

# Example of MQTT publishing function (if MQTT is enabled)
async def publish_mqtt_message(hass: HomeAssistant, topic: str, payload: str):
    """Publish a message to the MQTT broker."""
    if hass.data[DOMAIN].get(CONF_MQTT_ENABLED, False):
        mqtt_broker = hass.data[DOMAIN].get(CONF_MQTT_BROKER)
        mqtt_port = hass.data[DOMAIN].get(CONF_MQTT_PORT)
        mqtt_username = hass.data[DOMAIN].get(CONF_MQTT_USERNAME)
        mqtt_password = hass.data[DOMAIN].get(CONF_MQTT_PASSWORD)
        mqtt_base_topic = hass.data[DOMAIN].get(CONF_MQTT_BASE_TOPIC)

        full_topic = f"{mqtt_base_topic}/{topic}"

        # Publish to MQTT
        async_publish(
            hass,
            topic=full_topic,
            payload=payload,
            qos=0,
            retain=False
        )
        _LOGGER.info(f"Published message to MQTT topic {full_topic}: {payload}")
