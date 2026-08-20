"""
Provides classes for connection types like SSH or the API connections to GNS3 and ESXi.
These classes have methods which can be used to operate these APIs.
"""

__autor__ = "Leon Eiböck"
__date__ = "28/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import ipaddress
from abc import ABC, abstractmethod
from src.logger_adapter import get_logger

logger = get_logger()


class GenericConnection(ABC):
    def __init__(
        self, ip_address: str, port: int, username: str, password: str | None
    ) -> None:
        """
        :param ip_address: IP address of the instance
        :param port: Port number to connect to
        :param username: Hosts username
        :param password: corresponding password for user
        @TODO create pytest
        """
        ipaddress.ip_address(ip_address)

        self._ip_address = ip_address
        self._port = port
        self._username = username
        self._password = password

        self._connection = self.connect()

    def __getattr__(self, name: str):
        return getattr(self._connection, name)

    @property
    def ip_address(self) -> str:
        return self._ip_address

    @property
    def port(self) -> int:
        return self._port

    @property
    def username(self) -> str:
        return self._username

    @property
    def password(self) -> str | None:
        return self._password

    @property
    def connection(self):
        return self._connection

    @abstractmethod
    def connect(self) -> None:
        pass
