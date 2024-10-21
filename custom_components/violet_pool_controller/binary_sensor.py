import logging
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class VioletBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Violet Device Binary Sensor."""

    def __init__(self, coordinator, key, icon, config_entry):
        super().__init__(coordinator)
        self._key = key
        self._icon = icon
        self._config_entry = config_entry  # Store config_entry here
        self._attr_name = f"Violet {self._key}"
        self._attr_unique_id = f"{DOMAIN}_{self._key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "violet_pool_controller")},
            "name": "Violet Pool Controller",
            "manufacturer": "PoolDigital GmbH & Co. KG",
            "model": "Violet Model X",
            "sw_version": self.coordinator.data.get('fw') or self.coordinator.data.get('SW_VERSION', 'Unknown'),
            "configuration_url": f"http://{self._config_entry.data.get('host', 'Unknown IP')}",
        }
        self._has_logged_none_state = False  # To avoid repeated logs

    def _get_sensor_state(self):
        """Helper method to retrieve the current sensor state from the coordinator."""
        state = self.coordinator.data.get(self._key, None)
        
        if state is None:
            if not self._has_logged_none_state:
                _LOGGER.warning(f"Sensor {self._key} returned None as its state. Defaulting to 'OFF'.")
                self._has_logged_none_state = True  # Log once
            return False  # Default to OFF when state is None
        else:
            self._has_logged_none_state = False  # Reset log flag if state is valid
            return state == 1

    @property
    def is_on(self):
        """Return True if the binary sensor is on."""
        return self._get_sensor_state()

    @property
    def icon(self):
        """Return the icon for the binary sensor depending on its state."""
        return self._icon if self.is_on else f"{self._icon}-off"

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Violet Device binary sensors from a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    # Log the retrieved data for debugging purposes
    _LOGGER.debug(f"Violet Pool Controller API data: {coordinator.data}")

    # Initialize sensors from the BINARY_SENSORS list
    binary_sensors = [
        VioletBinarySensor(coordinator, sensor["key"], sensor["icon"], config_entry)
        for sensor in BINARY_SENSORS
    ]
    async_add_entities(binary_sensors)

BINARY_SENSORS = [
    {"name": "Pump State", "key": "PUMP_STATE", "icon": "mdi:water-pump"},
    {"name": "Solar State", "key": "SOLAR_STATE", "icon": "mdi:solar-power"},
    {"name": "Heater State", "key": "HEATER_STATE", "icon": "mdi:radiator"},
    {"name": "Light State", "key": "LIGHT_STATE", "icon": "mdi:lightbulb"},
]

