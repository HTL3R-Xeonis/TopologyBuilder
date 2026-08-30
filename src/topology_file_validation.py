"""
Module which contains classes and functions to handle and validate the contents of the config file
"""

__autor__ = "Leon Eiböck"
__date__ = "15/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from pathlib import Path
import yaml
from src.connections.api_handler import APIHandler
from loguru import logger


class TopologyFileValidation:
    """
    Class to handle and validate the contents of the config file
    """

    __VALID_ROLES = ["PC", "VM", "ROUTER", "SWITCH", "FW"]

    def __init__(self, path: str) -> None:
        """
        Initializes the ConfigFileHandler class
        :param path: Path to the YAML config-file

        :raises FileNotFoundError: Is thrown when the path does not exist.
        :raises TypeError: Is thrown when the path is not a string.
        :raises ValueError: Is thrown when the file is not a YAML file.
            May also be thrown when there is a template on GNS3 which has the same name as a template on ESXi and vice versa.
        :raises TimeoutError: Is thrown when a timeout occurs.
        """
        if not isinstance(path, str):
            logger.error(msg := f"Path must be a string. Current type: {type(path)}")
            raise TypeError(msg)
        if not Path(path).exists():
            logger.error(msg := f"File does not exists. Current path: {path}")
            raise FileNotFoundError(msg)
        if not Path(path).is_file() and not (
            path.endswith(".yml") or path.endswith(".yaml")
        ):
            logger.error(
                msg
                := f"Path does not link to *.yaml or *.yml file. Current path: {path}"
            )
            raise ValueError(msg)

        self.nodes: list[dict[str, str]] = []
        self.edges: list[list[str]] = []

        self._path = Path(path)
        self.__node_names = set()
        """Variable to ensure node names are unique."""
        self.__node_map = {}
        """Variable to ensure interfaces are not used twice per node."""
        self._available_templates = self.get_available_templates()

    @staticmethod
    def get_available_templates() -> set[str]:
        """
        Returns a set of all available templates which can be used as node images.
        Templates with same name on GNS3 and ESXi are not allowed, hence an ValueError will be raised.
        :return: Set of all available templates names.
        :raises TimeoutError: Is thrown when a timeout occurs.
        :raises ValueError: Is thrown when there is a template on GNS3 which has the same name as a template on ESXi and vice versa.
        """
        esxi_templates = APIHandler.get_esxi_template_names()
        gns3_templates = APIHandler.get_gns3_template_names()
        if esxi_templates & gns3_templates:
            logger.error(
                msg
                := f"Templates with the same name in GNS3 and ESXi are not allowed: {esxi_templates & gns3_templates}"
            )
            raise ValueError(msg)

        return esxi_templates | gns3_templates

    def read_file(self) -> dict:
        """
        Reads the contents of the YAML-file
        :return: The contents of the YAML-file as a dictionary
        :raises RuntimeError: Is thrown when an error occurs while trying to read the YAML-file.
        """
        try:
            with open(self._path, "r") as file:
                return yaml.safe_load(file)
        except Exception as e:
            logger.error(msg := f"Error reading file: {self._path}")
            raise RuntimeError(msg) from e

    def validate_file(self) -> None:
        """
        Validates the contents of the YAML-file as defined and makes nodes and edges available.
        :return:
        :raises KeyError: Is thrown when necessary keys are missing in the YAML-file.
        :raises TypeError: Is thrown when values are of the wrong type in the YAML-file.
        :raises ValueError: Is thrown when a value is not a valid option in the YAML-file or the format is incorrect.
        """
        content = self.read_file()
        if not {"edges", "nodes"} <= content.keys():
            logger.error(
                msg
                := f"Key 'edges' or 'nodes' not found in configuration file. Current keys: {list(content.keys())}"
            )
            raise KeyError(msg)

        self.nodes = content["nodes"]
        self.edges = content["edges"]

        if not isinstance(self.nodes, list):
            logger.error(
                msg := f"'nodes' must be of type list. Current type: {type(self.nodes)}"
            )
            raise TypeError(msg)
        if not isinstance(self.edges, list):
            logger.error(
                msg := f"'edges' must be of type list. Current type: {type(self.edges)}"
            )
            raise TypeError(msg)

        for node_group in self.nodes:
            self.__validate_node_group(node_group)
        for edge in self.edges:
            self.__validate_edges(edge)

    def __validate_node_group(self, node_group: dict) -> None:
        """
        Helper-methode for validate_file. Validates the nodegroup of given node.
        :param node_group: Dictionary entry of nodes. Contains the image, role and names.
        :return:
        :raises KeyError: Is thrown when necessary keys are missing in the YAML-file.
        :raises TypeError: Is thrown when values are of the wrong type in the YAML-file.
        :raises ValueError: Is thrown when a value is not a valid option in the YAML-file or the format is incorrect.
        """
        if not isinstance(node_group, dict):
            logger.error(
                msg
                := f"Node group must be of type dict. Current type: {type(node_group)}"
            )
            raise TypeError(msg)
        if not {"image", "role", "names"} <= node_group.keys():
            logger.error(
                msg
                := f"Key 'image', 'role' or 'names' not found in configuration file under 'nodes'. Current keys: {node_group.keys()}"
            )
            raise KeyError(msg)
        if not isinstance(node_group["image"], str):
            logger.error(
                msg
                := f"Image must be of type string. Current type: {type(node_group['image'])}"
            )
            raise TypeError(msg)
        if self._available_templates is not None:
            if node_group["image"] not in self._available_templates:
                logger.error(
                    msg := f"Image {node_group['image']} not found on ESXi or GNS3"
                )
                raise ValueError(msg)

        if not isinstance(node_group["role"], str):
            logger.error(
                msg
                := f"Role must be of type string. Current type: {type(node_group['role'])}"
            )
            raise TypeError(msg)
        if node_group["role"] not in self.__VALID_ROLES:
            logger.error(
                msg
                := f"{node_group['role']} is not a valid role. Valid roles: {self.__VALID_ROLES}"
            )
            raise ValueError(msg)

        names = node_group["names"]
        if names is None:
            return
        if not isinstance(names, list):
            logger.error(
                msg
                := f"Names must be of type list or None. Current type: {type(names)}"
            )
            raise TypeError(msg)
        for name in names:
            if not isinstance(name, str):
                logger.error(
                    msg
                    := f"Entries of 'names' must be of type str. Current type: {type(name)}"
                )
                raise TypeError(msg)
        if not len(names) == len(set(names)):
            logger.error(
                msg
                := f"Node names must be distinct. Not unique names: {set([n for n in names if names.count(n) > 1])}"
            )
            raise ValueError(msg)
        if set(names) & self.__node_names:
            logger.error(
                msg
                := f"Node names must be distinct. Not unique names: {set(names) & self.__node_names}"
            )
            raise ValueError(msg)
        self.__node_names.update(names)

    def __validate_edges(self, edge: list) -> None:
        """
        Helper-methode for validate_file. Validates the entries of given edge.
        :param edge: List entry of edges. Contains the connections between the nodes.
        :return:
        :raises ValueError: Is thrown when a value is not a valid option in the YAML-file or the format is incorrect.
        """
        if len(edge) != 4:
            logger.error(msg := "List of 'edges' must be of length 4")
            raise ValueError(msg)
        if not all(isinstance(v, str) for v in edge):
            logger.error(msg := f"Contents of 'edge' must be of type str: {edge}")
            raise ValueError(msg)
        if not {edge[0], edge[2]} <= self.__node_names:
            logger.error(msg := f"Name not defined in 'nodes': {edge[0]}, {edge[2]}")
            raise ValueError(msg)

        intf_list_1 = self.__node_map.get(edge[0], [])
        intf_list_2 = self.__node_map.get(edge[2], [])
        if edge[1] in intf_list_1:
            logger.error(
                msg := f"Interface {edge[1]} is used twice in edges of {edge[0]} node"
            )
            raise ValueError(msg)
        if edge[3] in intf_list_2:
            logger.error(
                msg := f"Interface {edge[3]} is used twice in edges of {edge[2]} node"
            )
            raise ValueError(msg)

        intf_list_1.append(edge[1])
        intf_list_2.append(edge[3])
        self.__node_map[edge[0]] = intf_list_1
        self.__node_map[edge[2]] = intf_list_2
