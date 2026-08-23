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
    """
    Base class for connection types like SSH or ESXi connections.
    """

    def __init__(self, ip: str, port: int, username: str, password: str | None) -> None:
        """
        :param ip: IP address of the instance
        :param port: Port number to connect to
        :param username: Hosts username
        :param password: corresponding password for user
        """
        if not self.is_valid_ipv4_address(ip):
            raise ValueError(f"Invalid IP address: {ip}")

        self._ip_address = ip
        self._port = port
        self._username = username
        self._password = password

        self._connection = self.connect()

    def __getattr__(self, name: str):
        return getattr(self._connection, name)

    @property
    def ip(self) -> str:
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

    @staticmethod
    def is_valid_ipv4_address(ip: str, ignore_loopback: bool = False) -> bool:
        """
        Checks if an IP address is a valid IPv4 address.
        An address is valid if it is a global, private or loopback, if ``ignore_loopback`` is ``false``, address.
        :param ip: the IP address to check
        :param ignore_loopback: Set to True if a loopback address is not valid.
        :return: Returns ``True`` if the IP address is a valid IPv4 address, ``False`` otherwise.
        """
        try:
            addr = ipaddress.ip_address(ip)
            if not addr.version == 4:
                return False
            return (
                addr.is_global
                or addr.is_private
                or (addr.is_loopback and not ignore_loopback)
            )
        except ValueError:
            return False
