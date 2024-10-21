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
        self._attr_is_on = self._get_sensor_state() == 1
        self._attr_icon = self._icon if self._attr_is_on else f"{self._icon}-off"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "violet_pool_controller")},
            "name": "Violet Pool Controller",
            "manufacturer": "PoolDigital GmbH & Co. KG",
            "model": "Violet Model X",
            "sw_version": self.coordinator.data.get('fw') or self.coordinator.data.get('SW_VERSION', 'Unbekannt'),
            "configuration_url": f"http://{self._config_entry.data.get('host', 'Unknown IP')}",
        }

    def _get_sensor_state(self):
        """Helper method to retrieve the current sensor state from the coordinator."""
        state = self.coordinator.data.get(self._key, None)
        if state is None:
            _LOGGER.warning(f"Sensor {self._key} returned None as its state.")
        return state

    @property
    def is_on(self):
        """Return True if the binary sensor is on."""
        return self._get_sensor_state() == 1

    @property
    def icon(self):
        """Return the icon for the binary sensor."""
        return self._icon if self.is_on else f"{self._icon}-off"

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Violet Device binary sensors from a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
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

