import atexit
import ipaddress
import ssl
from typing import Optional

from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim


class VMOrchestrator:
    def __init__(
        self,
        host: str,
        port: int = 443,
        username: str = None,
        password: str = None,
        verify_ssl: bool = False,
    ):
        self.host = host
        self.port = port

        ssl_context = ssl.create_default_context()

        if not verify_ssl:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        instance = SmartConnect(
            host=host, user=username, pwd=password, port=port, sslContext=ssl_context
        )

        atexit.register(Disconnect, instance)
        self.conn = instance

    def get_vm(self, vm_name: str) -> Optional[vim.VirtualMachine]:
        content = self.conn.RetrieveContent()

        container_view = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.VirtualMachine], True
        )

        try:
            for vm in container_view.view:
                if vm.name == vm_name:
                    return vm
        finally:
            container_view.Destroy()

        return None

    def get_vm_ip_address(self, vm_name: str) -> Optional[str]:
        for nic in self.get_vm(vm_name).guest.net or []:
            for address in nic.ipAddress or []:
                try:
                    parsed = ipaddress.ip_address(address)
                except ValueError:
                    continue

                if parsed.version != 4:
                    continue

                if parsed.is_loopback or parsed.is_link_local or parsed.is_multicast:
                    continue
                return address
        return None
