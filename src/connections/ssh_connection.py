from .generic_connection import GenericConnection
import paramiko


class SSHConnection(GenericConnection, paramiko.SSHClient):
    """
    Object which governs the SSH connection.
    """

    def connect(self) -> paramiko.SSHClient:
        """
        Connect to an SSH server.
        :return: Returns the client
        @TODO create pytest
        """
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        client.connect(
            hostname=self.ip,
            port=self.port,
            username=self.username,
            password=self.password,
            timeout=10,
        )

        return client
