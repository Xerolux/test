import logging
import aiohttp
import asyncio
from datetime import datetime, timedelta
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import async_timeout
import voluptuous as vol
from homeassistant.helpers import entity_platform
from homeassistant.helpers import config_validation as cv
from homeassistant.components.persistent_notification import create as persistent_notification_create

from .const import (
    DOMAIN, 
    API_SET_FUNCTION_MANUALLY
)

_LOGGER = logging.getLogger(__name__)

class VioletSwitch(CoordinatorEntity, SwitchEntity):
    def __init__(self, coordinator, key, name, icon):
        super().__init__(coordinator)
        self._key = key
        self._icon = icon
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}.violet.{self._key.lower()}"
        self.ip_address = coordinator.ip_address
        self.username = coordinator.username
        self.password = coordinator.password
        self.session = coordinator.session
        self.timeout = coordinator.timeout if hasattr(coordinator, 'timeout') else 10  # Customizable timeout
        self.auto_reset_time = None  # For automatic reset after duration
        self._cancel_auto_reset = None  # Cancel handle for auto-reset
        self._cache_duration = 10  # Cache for 10 seconds
        self._last_cache_update = None
        self._cached_state = None  # Cached state for last-minute caching

        if not all([self.ip_address, self.username, self.password]):
            _LOGGER.error(f"Missing credentials or IP address for switch {self._key}")
        else:
            _LOGGER.info(f"VioletSwitch for {self._key} initialized with IP {self.ip_address}")

    def _get_switch_state(self):
        """Fetches the current state of the switch, with last-minute caching."""
        now = datetime.now()
        if self._cached_state is not None and self._last_cache_update and (now - self._last_cache_update).total_seconds() < self._cache_duration:
            _LOGGER.debug(f"Returning cached state for {self._key}")
            return self._cached_state

        state = self.coordinator.data.get(self._key)
        self._cached_state = state
        self._last_cache_update = now
        return state

    @property
    def is_on(self):
        return self._get_switch_state() in (1, 4)

    @property
    def is_auto(self):
        return self._get_switch_state() == 0

    async def _send_command(self, action, duration=0, last_value=0):
        """Sends the control command to the API and handles retries with exponential backoff."""
        url = f"http://{self.ip_address}{API_SET_FUNCTION_MANUALLY}?{self._key},{action},{duration},{last_value}"
        auth = aiohttp.BasicAuth(self.username, self.password)

        retry_attempts = 3
        for attempt in range(retry_attempts):
            try:
                if attempt > 0:
                    wait_time = 2 ** attempt
                    _LOGGER.debug(f"Waiting {wait_time} seconds before retrying...")
                    await asyncio.sleep(wait_time)

                async with async_timeout.timeout(self.timeout):
                    async with self.session.get(url, auth=auth) as response:
                        response.raise_for_status()
                        response_text = await response.text()
                        lines = response_text.strip().split('\n')
                        if len(lines) >= 3 and lines[0] == "OK" and lines[1] == self._key and ("SWITCHED_TO" in lines[2] or "ON" in lines[2] or "OFF" in lines[2]):
                            _LOGGER.debug(f"Successfully sent {action} command to {self._key} with duration {duration} and last value {last_value}")
                            await self.coordinator.async_request_refresh()
                            return
                        else:
                            _LOGGER.error(f"Unexpected response from server when sending {action} command to {self._key}: {response_text}")
            except aiohttp.ClientResponseError as resp_err:
                _LOGGER.error(f"Response error when sending {action} command to {self._key}: {resp_err.status} {resp_err.message}")
            except aiohttp.ClientError as err:
                _LOGGER.error(f"Client error when sending {action} command to {self._key}: {err}")
            except asyncio.TimeoutError:
                _LOGGER.error(f"Timeout sending {action} command to {self._key}, attempt {attempt + 1} of {retry_attempts}")
            except Exception as err:
                _LOGGER.error(f"Unexpected error when sending {action} command to {self._key}: {err}")

        self._notify_user_of_failure(action, duration, last_value)

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        _LOGGER.debug(f"async_turn_on called for {self._key} with arguments: {kwargs}")
        duration = kwargs.get("duration", 0)
        last_value = kwargs.get("last_value", 0)
        await self._send_command("ON", duration, last_value)

        auto_delay = kwargs.get("auto_delay", 0)
        if auto_delay > 0:
            if self._cancel_auto_reset:
                _LOGGER.debug(f"Cancelling previous auto-reset for {self._key}")
                self._cancel_auto_reset()

            self.auto_reset_time = datetime.now() + timedelta(seconds=auto_delay)
            _LOGGER.debug(f"Auto-reset to AUTO after {auto_delay} seconds for {self._key}")

            self._cancel_auto_reset = asyncio.create_task(self._auto_reset(auto_delay))

    async def _auto_reset(self, auto_delay):
        """Handles the auto-reset to AUTO mode after the specified delay."""
        try:
            await asyncio.sleep(auto_delay)
            await self.async_turn_auto()
        except asyncio.CancelledError:
            _LOGGER.debug(f"Auto-reset for {self._key} was cancelled.")
            self._cancel_auto_reset = None

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        _LOGGER.debug(f"async_turn_off called for {self._key} with arguments: {kwargs}")
        last_value = kwargs.get("last_value", 0)
        await self._send_command("OFF", 0, last_value)

    async def async_turn_auto(self, **kwargs):
        """Set the switch to AUTO mode."""
        _LOGGER.debug(f"async_turn_auto called for {self._key} with arguments: {kwargs}")
        auto_delay = kwargs.get("auto_delay", 0)
        last_value = kwargs.get("last_value", 0)
        await self._send_command("AUTO", auto_delay, last_value)
        self.auto_reset_time = None

    @property
    def extra_state_attributes(self):
        """Return the extra state attributes for the switch."""
        attributes = super().extra_state_attributes or {}
        attributes['status_detail'] = "AUTO" if self.is_auto else "MANUAL"
        attributes['duration_remaining'] = self._get_switch_state() if not self.is_auto else "N/A"
        if self.auto_reset_time:
            remaining_time = (self.auto_reset_time - datetime.now()).total_seconds()
            attributes['auto_reset_in'] = max(0, remaining_time)
        else:
            attributes['auto_reset_in'] = "N/A"
        return attributes

    def _notify_user_of_failure(self, action, duration, last_value):
        """Send a notification to the user in case of repeated command failures."""
        message = (f"Failed to send {action} command to {self._key} after multiple attempts.\n"
                   f"Duration: {duration}, Last Value: {last_value}")
        title = f"{self._key} Command Failure"
        persistent_notification_create(self.hass, message, title)
        _LOGGER.warning(f"Sent notification to user: {message}")

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Violet switches based on config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    available_switches = [switch for switch in SWITCHES if switch["key"] in coordinator.data]
    switches = [
        VioletSwitch(coordinator, switch["key"], switch["name"], switch["icon"])
        for switch in available_switches
    ]
    async_add_entities(switches)

    # Register entity-specific services using async_register_entity_service
    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        "turn_auto",
        {
            vol.Optional("auto_delay", default=0): vol.Coerce(int),
            vol.Optional("last_value", default=0): vol.Coerce(int),
        },
        "async_turn_auto"
    )

    platform.async_register_entity_service(
        "turn_on",
        {
            vol.Optional("duration", default=0): vol.Coerce(int),
            vol.Optional("last_value", default=0): vol.Coerce(int),
        },
        "async_turn_on"
    )

    platform.async_register_entity_service(
        "turn_off",
        {},
        "async_turn_off"
    )

SWITCHES = [
    {"name": "Violet Pump", "key": "PUMP", "icon": "mdi:water-pump"},
    {"name": "Violet Light", "key": "LIGHT", "icon": "mdi:lightbulb"},
]


