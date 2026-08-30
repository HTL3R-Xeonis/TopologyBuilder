from src.connections.generic_connection import GenericConnection
import paramiko
from loguru import logger


class SSHConnection(GenericConnection, paramiko.SSHClient):
    """
    Object which governs the SSH connection.
    """

    def __init__(self, ip, port, username, password):
        """
        :param ip: IP address of the instance
        :param port: Port number to connect to
        :param username: Hosts username
        :param password: corresponding password for user
        :raises ValueError: Is thrown when the IPv4 address is not a public, private or loopback address. Is also thrown when the credentials are not valid.
        :raises TypeError: Is thrown when the parameters are of the wrong types.
        :raises TimeoutError: Is thrown when the connection buildup takes too long.
        :raises ConnectionError: Is thrown when the connection fails.
        """
        super().__init__(ip, port, username, password)

    def connect(self) -> paramiko.SSHClient:
        """
        Connect to an SSH server.
        :return: Returns the client
        :raises TimeoutError: Is thrown when the connection buildup takes too long.
        :raises ValueError: Is thrown when the credentials are not valid.
        :raises ConnectionError: Is thrown when the connection fails.
        """
        try:
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            client.connect(
                hostname=self.ip,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=5,
            )

            return client
        except TimeoutError:
            logger.error(msg := f"Connection to {self.ip}:{self.port} timed out.")
            raise TimeoutError(msg)
        except paramiko.AuthenticationException as exc:
            logger.error(msg := f"Invalid credentials for host: {self.ip}")
            raise ValueError(msg) from exc
        except paramiko.ssh_exception.NoValidConnectionsError as exc:
            logger.error(msg := f"Connection refused to host: {self.ip}:{self.port}")
            raise ConnectionError(msg) from exc
        except paramiko.BadHostKeyException as exc:
            logger.error(
                msg := f"Could not verifiy servers host key: {self.ip}:{self.port}"
            )
            raise ConnectionError(msg) from exc
        except Exception as exc:
            logger.error(msg := f"Connection to {self.ip}:{self.port} failed: {exc}")
            raise ConnectionError(msg) from exc
