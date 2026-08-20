from src.connection_handler.generic_connection import GenericConnection
import paramiko


class SSHConnection(GenericConnection, paramiko.SSHClient):
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
            hostname=self.ip_address,
            port=22,
            username=self.username,
            password=self.password,
            timeout=10,
        )

        return client

    def upload_file(self, file_path: str, upload_path: str):
        with self.connection.open_sftp() as sftp:
            sftp.put(file_path, upload_path)
