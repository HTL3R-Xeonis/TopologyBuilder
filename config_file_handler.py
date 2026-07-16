"""
Module which contains classes and functions to handle and validate the contents of the config file
"""

__autor__ = "Leon Eiböck"
__date__ = "15/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from pathlib import Path
import yaml
from logger_adapter import get_logger

logger = get_logger()


class ConfigFileHandler:
    """
    Class to handle and validate the contents of the config file
    """

    __VALID_ROLES = ["PC", "LINUX", "ROUTER", "SWITCH", "FW"]
    __NODE_NAMES = set()

    def __init__(self, path: str) -> None:
        """
        Initializes the ConfigFileHandler class
        :param path: Path to the YAML config-file
        >>> config = ConfigFileHandler("./config_file_example.yml")
        """
        if not isinstance(path, str):
            raise logger.alert(
                TypeError, f"Path must be a string. Current type: {type(path)}"
            )
        if not Path(path).exists():
            raise logger.alert(
                FileNotFoundError, f"File does not exists. Current path: {path}"
            )
        self.path = Path(path)

    def read_file(self) -> dict:
        """
        Reads the contents of the YAML-file
        :return: The contents of the YAML-file as a dictionary

        >>> config = ConfigFileHandler("./config_file_example.yml")
        >>> config.read_file().keys()
        dict_keys(['nodes', 'edges'])
        """
        try:
            with open(self.path, "r") as file:
                return yaml.safe_load(file)
        except Exception as e:
            raise logger.alert(e, f"Error reading file: {self.path}")

    def validate_file(self) -> None:
        """
        Validates the contents of the YAML-file as defined and makes nodes and edges available.
        :return:
        >>> config = ConfigFileHandler("./config_file_example.yml")
        >>> config.validate_file()

        #TODO make UNIT tests
        """
        content = self.read_file()
        if not {"edges", "nodes"} <= content.keys():
            raise logger.alert(
                KeyError,
                f"Key 'edges' or 'nodes' not found in configuration file. Current keys: {content.keys()}",
            )

        self.nodes = content["nodes"]
        self.edges = content["edges"]

        if not isinstance(self.nodes, list):
            raise logger.alert(
                TypeError,
                f"'nodes' must be of type list. Current type: {type(self.nodes)}",
            )
        if not isinstance(self.edges, list):
            raise logger.alert(
                TypeError,
                f"'edges' must be of type list. Current type: {type(self.edges)}",
            )

        for node_groupe in self.nodes:
            self.__validate_node_group(node_groupe)
        for edge in self.edges:
            self.__validate_edges(edge)

    def __validate_node_group(self, node_group: dict) -> None:
        """
        Helper-methode for validate_file. Validates the nodegroup of given node.
        :param node_group: Dictionary entry of nodes. Contains the image, role and names.
        :return:
        #TODO make UNIT tests
        """
        if not isinstance(node_group, dict):
            raise logger.alert(
                TypeError,
                f"Node group must be of type dict. Current type: {type(node_group)}",
            )
        if not {"image", "role", "names"} <= node_group.keys():
            raise logger.alert(
                KeyError,
                f"Key 'image', 'role' or 'names' not found in configuration file under 'nodes'. Current keys: {node_group.keys()}",
            )
        if node_group["image"] is None:
            raise logger.alert(ValueError, "Image must be defined in config_file")
        if not isinstance(node_group["image"], str):
            raise logger.alert(
                TypeError,
                f"Image must be of type string. Current type: {type(node_group['image'])}",
            )
        if node_group["role"] not in self.__VALID_ROLES:
            raise logger.alert(
                ValueError,
                f"{node_group['role']} is not a valid role. Valid roles: {self.__VALID_ROLES}",
            )

        names = node_group["names"]
        if names is None:
            return
        if not isinstance(names, list):
            raise logger.alert(
                TypeError,
                f"Names must be of type list or None. Current type: {type(names)}",
            )
        for name in names:
            if not isinstance(name, str):
                raise logger.alert(
                    TypeError,
                    f"Entries of 'names' must be of type str. Current type: {type(name)}",
                )
        if not len(names) == len(set(names)):
            raise logger.alert(
                ValueError,
                f"Node names must be distinct. Not unique names: {set([n for n in names if names.count(n) > 1])}",
            )
        if set(names) & self.__NODE_NAMES:
            raise logger.alert(
                ValueError,
                f"Node names must be distinct. Not unique names: {set(names) & self.__NODE_NAMES}",
            )
        self.__NODE_NAMES.update(names)

    def __validate_edges(self, edge: list) -> None:
        """
        Helper-methode for validate_file. Validates the entries of given edge.
        :param edge: List entry of edges. Contains the connections between the nodes.
        :return:
        #TODO make UNIT tests
        """
        if len(edge) != 4:
            raise logger.alert(ValueError, "List of 'edges' must be of length 4")
        if not {edge[0], edge[2]} <= self.__NODE_NAMES:
            raise logger.alert(
                ValueError, f"Name not defined in 'nodes': {edge[0]}, {edge[2]}"
            )
        # TODO validate Interfaces, if ip-Address and option is set
