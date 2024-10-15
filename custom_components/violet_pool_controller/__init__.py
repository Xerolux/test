import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from datetime import timedelta
import async_timeout
import aiohttp
import asyncio
from typing import Any, Dict

from .const import (
    DOMAIN, 
    CONF_API_URL, 
    CONF_POLLING_INTERVAL, 
    CONF_USE_SSL, 
    CONF_DEVICE_ID,
    CONF_USERNAME, 
    CONF_PASSWORD,
    DEFAULT_POLLING_INTERVAL, 
    DEFAULT_USE_SSL,
    API_READINGS,
    API_SET_FUNCTION_MANUALLY
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Violet Pool Controller from a config entry."""
    
    # Retrieve configuration data from the config entry
    config = {
        "ip_address": entry.data[CONF_API_URL],
        "polling_interval": entry.data.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL),
        "use_ssl": entry.data.get(CONF_USE_SSL, DEFAULT_USE_SSL),
        "device_id": entry.data.get(CONF_DEVICE_ID, 1),
        "username": entry.data.get(CONF_USERNAME),
        "password": entry.data.get(CONF_PASSWORD)
    }

    # Log configuration data
    _LOGGER.info(f"Setting up Violet Pool Controller with config: {config}")

    # Get a shared aiohttp session
    session = aiohttp_client.async_get_clientsession(hass)

    # Create a coordinator for data updates
    coordinator = VioletDataUpdateCoordinator(
        hass,
        config=config,
        session=session,
    )

    # Log before first data fetch
    _LOGGER.debug("First data fetch for Violet Pool Controller is being performed")

    try:
        # Ensure the first data fetch happens during setup
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        _LOGGER.error(f"First data fetch failed: {err}")
        return False

    # Store the coordinator in hass.data for access by platform files
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Register the custom service for 'turn_auto' with specific switch
    async def handle_turn_auto_service(call):
        """Handle the custom turn_auto service for specific switches."""
        switch = call.data.get("switch")  # Name of the switch (e.g., 'PUMP', 'LIGHT', etc.)
        auto_delay = call.data.get("auto_delay", 0)  # Duration for AUTO mode
        last_value = call.data.get("last_value", 0)  # Last value parameter (e.g., speed for PUMP)

        _LOGGER.info(f"Setting {switch} to AUTO mode with delay {auto_delay} seconds and last value {last_value}")

        await coordinator.turn_auto(switch, auto_delay, last_value)

    # Register the service for AUTO
    hass.services.async_register(DOMAIN, "turn_auto", handle_turn_auto_service)

    # Register the custom service for 'turn_on' with specific switch
    async def handle_turn_on_service(call):
        """Handle the custom turn_on service for specific switches."""
        switch = call.data.get("switch")  # Name of the switch (e.g., 'PUMP', 'LIGHT', etc.)
        duration = call.data.get("duration", 0)  # Duration for ON mode
        last_value = call.data.get("last_value", 0)  # Last value parameter (e.g., speed for PUMP)

        _LOGGER.info(f"Setting {switch} to ON mode with duration {duration} seconds and last value {last_value}")

        await coordinator.turn_on(switch, duration, last_value)

    # Register the service for ON
    hass.services.async_register(DOMAIN, "turn_on", handle_turn_on_service)

    # Register the custom service for 'turn_off' with specific switch
    async def handle_turn_off_service(call):
        """Handle the custom turn_off service for specific switches."""
        switch = call.data.get("switch")  # Name of the switch (e.g., 'PUMP', 'LIGHT', etc.)

        _LOGGER.info(f"Setting {switch} to OFF mode")

        await coordinator.turn_off(switch)

    # Register the service for OFF
    hass.services.async_register(DOMAIN, "turn_off", handle_turn_off_service)

    # Forward setup to platforms (e.g., switch, sensor, binary sensor)
    await hass.config_entries.async_forward_entry_setups(entry, ["switch", "sensor", "binary_sensor"])

    _LOGGER.info("Violet Pool Controller setup completed successfully")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, ["switch", "sensor", "binary_sensor"]
    )

    # Remove the coordinator from hass.data
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    _LOGGER.info(f"Violet Pool Controller (device {entry.entry_id}) unloaded successfully")
    return unload_ok


class VioletDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Violet Pool Controller data and dynamically adding new entities."""

    def __init__(self, hass: HomeAssistant, config: Dict[str, Any], session: aiohttp.ClientSession) -> None:
        """Initialize the coordinator."""
        self.ip_address: str = config["ip_address"]
        self.username: str = config["username"]
        self.password: str = config["password"]
        self.session: aiohttp.ClientSession = session
        self.use_ssl: bool = config["use_ssl"]
        self.device_id: int = config["device_id"]

        _LOGGER.info(f"Initializing data coordinator for device {self.device_id} (IP: {self.ip_address}, SSL: {self.use_ssl})")

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self.device_id}",
            update_interval=timedelta(seconds=config["polling_interval"]),
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from the Violet Pool Controller API."""
        # Same as before (unchanged)
        pass

    async def turn_auto(self, switch: str, auto_delay: int, last_value: int):
        """Send the command to turn a specific switch to AUTO mode."""
        protocol = "https" if self.use_ssl else "http"
        url = f"{protocol}://{self.ip_address}{API_SET_FUNCTION_MANUALLY}"

        command = f"?{switch},AUTO,{auto_delay},{last_value}"
        full_url = f"{url}{command}"
        _LOGGER.info(f"Sending AUTO command for {switch} to {self.ip_address} with delay {auto_delay} and last value {last_value}")

        try:
            auth = aiohttp.BasicAuth(self.username, self.password) if self.username and self.password else None

            async with async_timeout.timeout(10):
                async with self.session.get(full_url, auth=auth, ssl=self.use_ssl) as response:
                    _LOGGER.debug(f"Response from AUTO command for {switch}: {await response.text()}")
                    response.raise_for_status()
        except Exception as e:
            _LOGGER.error(f"Error while setting AUTO mode for {switch}: {e}")

    async def turn_on(self, switch: str, duration: int, last_value: int):
        """Send the command to turn a specific switch ON."""
        protocol = "https" if self.use_ssl else "http"
        url = f"{protocol}://{self.ip_address}{API_SET_FUNCTION_MANUALLY}"

        command = f"?{switch},ON,{duration},{last_value}"
        full_url = f"{url}{command}"
        _LOGGER.info(f"Sending ON command for {switch} to {self.ip_address} with duration {duration} and last value {last_value}")

        try:
            auth = aiohttp.BasicAuth(self.username, self.password) if self.username and self.password else None

            async with async_timeout.timeout(10):
                async with self.session.get(full_url, auth=auth, ssl=self.use_ssl) as response:
                    _LOGGER.debug(f"Response from ON command for {switch}: {await response.text()}")
                    response.raise_for_status()
        except Exception as e:
            _LOGGER.error(f"Error while setting ON mode for {switch}: {e}")

    async def turn_off(self, switch: str):
        """Send the command to turn a specific switch OFF."""
        protocol = "https" if self.use_ssl else "http"
        url = f"{protocol}://{self.ip_address}{API_SET_FUNCTION_MANUALLY}"

        command = f"?{switch},OFF,0,0"
        full_url = f"{url}{command}"
        _LOGGER.info(f"Sending OFF command for {switch} to {self.ip_address}")

        try:
            auth = aiohttp.BasicAuth(self.username, self.password) if self.username and self.password else None

            async with async_timeout.timeout(10):
                async with self.session.get(full_url, auth=auth, ssl=self.use_ssl) as response:
                    _LOGGER.debug(f"Response from OFF command for {switch}: {await response.text()}")
                    response.raise_for_status()
        except Exception as e:
            _LOGGER.error(f"Error while setting OFF mode for {switch}: {e}")

