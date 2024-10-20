import logging
import aiohttp
import async_timeout
from datetime import datetime, timedelta
from homeassistant.helpers.entity import Entity
from homeassistant.const import CONF_DEVICE_ID, CONF_API_URL, CONF_POLLING_INTERVAL
from .const import DOMAIN, CONF_DEVICE_NAME

RETRY_LIMIT = 3  # Maximum number of retries for API requests
CACHE_DURATION = timedelta(seconds=10)  # Time to cache API responses

class VioletPoolControllerEntity(Entity):
    """Base class for a Violet Pool Controller entity."""

    def __init__(self, config_entry, api_data, entity_description):
        """Initialize the entity."""
        self.config_entry = config_entry
        self.api_data = api_data
        self.entity_description = entity_description
        self._name = f"{config_entry.data.get(CONF_DEVICE_NAME)} {entity_description.name}"
        self._unique_id = f"{config_entry.data.get(CONF_DEVICE_ID)}_{entity_description.key}"
        self._state = None
        self._available = True
        self._last_update_successful = False
        self._last_error = None
        self._retry_attempts = 0
        self.api_url = config_entry.data.get(CONF_API_URL)
        self.polling_interval = config_entry.data.get(CONF_POLLING_INTERVAL)
        self._last_updated = None
        self._cache_expiry = None
        self._cached_data = None
        self._logger = logging.getLogger(f"{DOMAIN}.{self._unique_id}")
        self._icon = entity_description.icon

        self._logger.info(f"Initialized {self._name} with unique ID: {self._unique_id}")

    @property
    def name(self):
        """Return the name of the entity."""
        return self._name

    @property
    def unique_id(self):
        """Return the unique ID of the entity."""
        return self._unique_id

    @property
    def available(self):
        """Return if the entity is available."""
        return self._available

    @property
    def state(self):
        """Return the state of the entity."""
        return self._state

    @property
    def icon(self):
        """Return the custom icon for the entity."""
        return self._icon

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {
            "polling_interval": self.polling_interval,
            "api_url": self.api_url,
            "last_update": self._last_updated,
            "last_error": self._last_error,
            "retry_attempts": self._retry_attempts,
        }

    async def async_update(self):
        """Fetch new state data for the entity from the API."""
        now = datetime.utcnow()
        
        # Check cache
        if self._cached_data and self._cache_expiry and now < self._cache_expiry:
            self._logger.debug(f"Using cached data for {self._name}")
            self._update_state(self._cached_data)
            return

        for attempt in range(RETRY_LIMIT):
            try:
                # Perform API request with timeout
                self._logger.debug(f"Fetching data for {self._name} from API. Attempt {attempt + 1}/{RETRY_LIMIT}")
                async with async_timeout.timeout(10):
                    response = await self.api_data.get_data()

                # Cache the response
                self._cached_data = response
                self._cache_expiry = now + CACHE_DURATION

                # Process response
                if response and self.entity_description.key in response:
                    self._update_state(response)
                    self._available = True
                    self._last_update_successful = True
                    self._last_error = None
                    self._retry_attempts = 0
                    self._logger.debug(f"Updated {self._name} state: {self._state}")
                    return
                else:
                    self._available = False
                    self._last_error = f"No data for {self.entity_description.key} in response."
                    self._logger.warning(f"{self._last_error}")
                    return

            except aiohttp.ClientError as e:
                self._logger.error(f"Client error updating {self.name}: {e}")
                self._last_error = str(e)
                self._retry_attempts += 1
                self._available = False

            except asyncio.TimeoutError:
                self._logger.error(f"Timeout error updating {self.name}. Attempt {attempt + 1}/{RETRY_LIMIT}")
                self._last_error = "Timeout"
                self._retry_attempts += 1
                self._available = False

            except KeyError as e:
                self._logger.error(f"Missing key {e} in the API response for {self.name}")
                self._last_error = f"Missing key {e}"
                self._available = False
                return

            except Exception as e:
                self._logger.error(f"Unexpected error updating {self.name}: {e}")
                self._last_error = str(e)
                self._available = False
                return

            await asyncio.sleep(1)  # Short pause before retry

        self._logger.error(f"Failed to update {self.name} after {RETRY_LIMIT} attempts.")

    def _update_state(self, response):
        """Update the state from the API response."""
        try:
            self._state = response.get(self.entity_description.key)
            self._last_updated = datetime.utcnow()
            self._logger.debug(f"New state for {self.name}: {self._state}")
        except KeyError:
            self._logger.error(f"Key {self.entity_description.key} not found in response.")
            self._available = False

