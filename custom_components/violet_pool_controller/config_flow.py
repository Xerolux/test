import logging
import aiohttp
import async_timeout
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import aiohttp_client
import re  # Für die Validierung der Firmware-Version
from .const import (
    DOMAIN,
    CONF_API_URL,
    CONF_POLLING_INTERVAL,
    CONF_USE_SSL,
    CONF_DEVICE_NAME,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_DEVICE_ID,
    DEFAULT_POLLING_INTERVAL,
    DEFAULT_USE_SSL,
    API_READINGS,  # API endpoint
)

_LOGGER = logging.getLogger(__name__)

# Validierung der Firmware-Version
def is_valid_firmware(firmware_version):
    """Validiere, ob die Firmware-Version im richtigen Format vorliegt (z.B. 1.23)."""
    return bool(re.match(r'^\d+\.\d+$', firmware_version))

class VioletDeviceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Violet Pool Controller."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            base_ip = user_input[CONF_API_URL]  # Only the IP address is entered
            use_ssl = user_input.get(CONF_USE_SSL, DEFAULT_USE_SSL)
            protocol = "https" if use_ssl else "http"

            # Dynamisch erstellte vollständige API-URL
            api_url = f"{protocol}://{base_ip}{API_READINGS}"
            _LOGGER.debug("Constructed API URL: %s", api_url)

            device_name = user_input.get(CONF_DEVICE_NAME, "Violet Pool Controller")
            username = user_input.get(CONF_USERNAME)
            password = user_input.get(CONF_PASSWORD)
            device_id = user_input.get(CONF_DEVICE_ID, 1)

            await self.async_set_unique_id(base_ip)  # Use the base IP as the unique ID
            self._abort_if_unique_id_configured()

            session = aiohttp_client.async_get_clientsession(self.hass)

            # Ping vor vollständiger Anfrage, um Verfügbarkeit zu prüfen
            try:
                async with session.get(f"{protocol}://{base_ip}/ping", auth=aiohttp.BasicAuth(username, password), ssl=use_ssl) as ping_response:
                    ping_response.raise_for_status()
                _LOGGER.debug("API-Ping erfolgreich")
            except aiohttp.ClientError as err:
                _LOGGER.error("API-Ping fehlgeschlagen bei %s: %s", base_ip, err)
                errors["base"] = "cannot_connect"
                raise ValueError("API-Ping fehlgeschlagen.")

            # Timeout-Dauer dynamisch anpassen, um Ressourcen zu sparen
            timeout_duration = user_input.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL)
            if timeout_duration < 5:
                timeout_duration = 5  # Setze Minimum-Timeout
            elif timeout_duration > 60:
                timeout_duration = 60  # Begrenze auf 60 Sekunden

            retry_attempts = 3  # Wiederholungsversuche bei Verbindungsfehlern
            for attempt in range(retry_attempts):
                try:
                    async with async_timeout.timeout(timeout_duration):
                        auth = aiohttp.BasicAuth(username, password)
                        _LOGGER.debug(
                            "Versuche, eine Verbindung zur API bei %s herzustellen (SSL=%s)",
                            api_url,
                            use_ssl,
                        )

                        async with session.get(api_url, auth=auth, ssl=use_ssl) as response:
                            response.raise_for_status()
                            data = await response.json()
                            _LOGGER.debug("API-Antwort empfangen: %s", data)

                            # Dynamische Suche nach möglichen Schlüsseln der Firmware
                            possible_keys = ['fw', 'firmware', 'version', 'firmware_version']
                            firmware_version = next((data.get(key) for key in possible_keys if data.get(key)), None)

                            if not firmware_version:
                                _LOGGER.error("Firmware-Version in der API-Antwort nicht gefunden: %s", data)
                                errors["base"] = "firmware_not_found"
                                raise ValueError("Firmware-Version nicht gefunden.")
                            else:
                                if is_valid_firmware(firmware_version):
                                    _LOGGER.info("Firmware-Version erfolgreich ausgelesen und validiert: %s", firmware_version)
                                else:
                                    _LOGGER.error("Ungültige Firmware-Version: %s", firmware_version)
                                    errors["base"] = "invalid_firmware"
                                    raise ValueError("Ungültige Firmware-Version.")

                        # Beende die Schleife bei erfolgreicher API-Abfrage
                        break
                except aiohttp.ClientConnectionError as err:
                    _LOGGER.error("Verbindungsfehler zur API bei %s: %s", api_url, err)
                    errors["base"] = "connection_error"
                    if attempt + 1 == retry_attempts:
                        raise ValueError("Verbindungsfehler nach mehreren Versuchen.")
                except aiohttp.ClientResponseError as err:
                    _LOGGER.error("Fehlerhafte API-Antwort erhalten (Statuscode: %s): %s", err.status, err.message)
                    errors["base"] = "invalid_response"
                    break
                except asyncio.TimeoutError:
                    _LOGGER.error("Zeitüberschreitung bei der API-Anfrage.")
                    errors["base"] = "timeout"
                    break
                except Exception as err:
                    _LOGGER.error("Unerwartete Ausnahme: %s", err)
                    errors["base"] = "unknown"
                    break

            if not errors:
                # Nur die IP-Adresse speichern, um unnötige Daten zu vermeiden
                user_input[CONF_API_URL] = base_ip
                user_input[CONF_DEVICE_NAME] = device_name
                user_input[CONF_USERNAME] = username
                user_input[CONF_PASSWORD] = password
                user_input[CONF_DEVICE_ID] = device_id

                # Erfolgreiche Konfiguration
                return self.async_create_entry(
                    title=f"{device_name} (ID {device_id})", data=user_input
                )

        # Formular für den Benutzer anzeigen
        data_schema = vol.Schema({
            vol.Required(CONF_API_URL): str,  # Nur die IP-Adresse wird eingegeben
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional(CONF_POLLING_INTERVAL, default=DEFAULT_POLLING_INTERVAL): vol.All(vol.Coerce(int), vol.Range(min=5, max=3600)),
            vol.Optional(CONF_USE_SSL, default=DEFAULT_USE_SSL): bool,
            vol.Optional(CONF_DEVICE_NAME, default="Violet Pool Controller"): str,
            vol.Required(CONF_DEVICE_ID, default=1): vol.All(vol.Coerce(int), vol.Range(min=1)),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for the Violet device."""
        return VioletOptionsFlow(config_entry)

class VioletOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Violet Device."""

    def __init__(self, config_entry):
        """Initialize options flow."""
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
        })

        return self.async_show_form(
            step_id="user",
            data_schema=options_schema
        )
