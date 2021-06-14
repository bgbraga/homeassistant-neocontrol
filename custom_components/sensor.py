import logging
from homeassistant.helpers.entity import Entity
import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util.dt import utcnow as dt_utcnow, as_local
import voluptuous as vol
import requests
import asyncio
from requests.adapters import HTTPAdapter
from datetime import datetime, timedelta, date
import time
import socket

CONF_PORT = 'port'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_PORT, default='8760'): cv.string
})


SCAN_INTERVAL = timedelta(minutes=5)
_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    port = config[CONF_PORT]

    #sensor init
    sensor = NeocontrolSensor("Neocontrol", hass, port)


class NeocontrolSensor(Entity):
    """Representation of a Sensor."""

    def __init__(self, sensor_name, hass, port):
        """Initialize the sensor."""
        self._state = None
        self._name = sensor_name
        self._hass = hass
        self._port = port
        self._multicast_addr = "255.255.255.255"
        self._buffer_size = 1024
        self._client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)  # UDP
        self.LAST_STATUS = {}

        MULTICAST_TTL = 2

        self._client.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL)
        self._client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._client.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)  # Enable broadcasting mode

        self._client.bind(("", self._port))

        self._monitoring()

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def state_attributes(self):
        """Return the device state attributes."""
        return self._attributes

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._metadata[1]

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return self._metadata[2]

    @property
    def available(self, utc_now=None):
        return True

    async def async_update(self):
        """Fetch new state data for the sensor.
        This is the only method that should fetch new data for Home Assistant.
        """

        await self.status_request()

    async def status_request(self):
        bytesToSend = bytearray([10, 0, 255])  # module status
        self._client.sendto(bytesToSend, (self._multicast_addr, self._port))

    async def monitoring(self):
        while True:
            data, addr = self._client.recvfrom(self._buffer_size)
            print("received message: %s from %s" % (data, addr))
            data2 = [b'%x' % i for i in data]

            #se começar com 64 e depois 0 é a resposta do status do módulo
            if data2[0] == b'64' and data2[1] == b'0':
                module = {}
                #nome do modulo é o que tem antes de espaço
                name = ''
                for idx, item in enumerate(data2[2:]):
                    if item == b'20':
                        break
                    name += chr(int(item.decode("utf-8"), 16))
                module['name'] = name

                #status de cada canal
                switch_start = idx+5
                for idx, item in enumerate(data2[switch_start:-1]):
                    module['channel_'+str(idx+1)] = item.decode(encoding="utf-8")

                self.check_status(module)
            time.sleep(1)

    def check_status(self, module):
        changed = False
        if module['name'] in self.LAST_STATUS:
            changed = self.is_changed_status(self.LAST_STATUS[module['name']], module)
        else:
            self.LAST_STATUS[module['name']] = module
            changed = True

        if changed:
            self.update_status(module)

    def is_changed_status(self, last_status, new_status):
        # verifica os 8 canais
        for i in range(1, 8):
            if last_status['channel_'+str(i)] != new_status['channel_'+str(i)]:
                return True

        return False

    def update_status(self, module):
        _LOGGER.debug('vai fazer update na plataforma:')
        _LOGGER.debug(module)