import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, API_SET_FUNCTION_MANUALLY

_LOGGER = logging.getLogger(__name__)

class VioletSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a switch that controls various functions of the Violet Pool Controller."""

    def __init__(self, coordinator, key, name, icon):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._key = key
        self._icon = icon
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{self._key}"
        self.ip_address = coordinator.ip_address
        self.username = coordinator.username
        self.password = coordinator.password
        self.session = coordinator.session
        self.timeout = coordinator.timeout if hasattr(coordinator, 'timeout') else 10

    @property
    def is_on(self):
        """Return true if the switch is on."""
        return self.coordinator.data.get(self._key) in (1, 4)

    @property
    def is_auto(self):
        """Return true if the switch is in auto mode."""
        return self.coordinator.data.get(self._key) == 0

    async def _send_command(self, action, duration=0, last_value=0):
        """Send the control command to the API."""
        url = f"http://{self.ip_address}{API_SET_FUNCTION_MANUALLY}?{self._key},{action},{duration},{last_value}"
        auth = aiohttp.BasicAuth(self.username, self.password)
        
        try:
            async with self.session.get(url, auth=auth, timeout=self.timeout) as response:
                response.raise_for_status()
                _LOGGER.info(f"Sent {action} command to {self._key} with duration {duration} and last_value {last_value}")
                await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error(f"Failed to send {action} command to {self._key}: {e}")

    async def async_turn_on(self, **kwargs):
        """Turn the switch on with optional duration and last_value."""
        duration = kwargs.get('duration', 0)
        last_value = kwargs.get('last_value', 0)
        await self._send_command("ON", duration, last_value)

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        last_value = kwargs.get('last_value', 0)
        await self._send_command("OFF", 0, last_value)

    async def async_turn_auto(self, **kwargs):
        """Set the switch to auto mode."""
        auto_delay = kwargs.get('auto_delay', 0)
        last_value = kwargs.get('last_value', 0)
        await self._send_command("AUTO", auto_delay, last_value)

    @property
    def icon(self):
        """Return the icon depending on the switch's state."""
        if self._key == "PUMP":
            return "mdi:water-pump" if self.is_on else "mdi:water-pump-off"
        elif self._key == "LIGHT":
            return "mdi:lightbulb-on" if self.is_on else "mdi:lightbulb"
        elif self._key == "ECO":
            return "mdi:leaf" if self.is_on else "mdi:leaf-off"
        elif self._key in ["DOS_1_CL", "DOS_4_PHM"]:
            return "mdi:flask" if self.is_on else "mdi:flask-outline"
        elif "EXT" in self._key:
            return "mdi:power-socket" if self.is_on else "mdi:power-socket-off"
        return self._icon

    @property
    def extra_state_attributes(self):
        """Return the extra state attributes for the switch."""
        attributes = super().extra_state_attributes or {}
        attributes['status_detail'] = "AUTO" if self.is_auto else "MANUAL"
        attributes['duration_remaining'] = self.coordinator.data.get(self._key) if not self.is_auto else "N/A"
        return attributes

    @property
    def device_info(self):
        """Return device information for the Violet Pool Controller."""
        return {
            "identifiers": {(DOMAIN, "violet_pool_controller")},
            "name": "Violet Pool Controller",
            "manufacturer": "PoolDigital GmbH & Co. KG",
            "model": "Violet Model X",
            "sw_version": self.coordinator.data.get('fw') or self.coordinator.data.get('SW_VERSION', 'Unknown'),
        }

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Violet switches based on config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    available_switches = [switch for switch in SWITCHES if switch["key"] in coordinator.data]
    switches = [
        VioletSwitch(coordinator, switch["key"], switch["name"], switch["icon"])
        for switch in available_switches
    ]
    async_add_entities(switches)

SWITCHES = [
    {"name": "Pump Switch", "key": "PUMP", "icon": "mdi:water-pump"},
    {"name": "Light Switch", "key": "LIGHT", "icon": "mdi:lightbulb"},
]
