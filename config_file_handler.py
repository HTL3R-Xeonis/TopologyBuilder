"""
Module which contains classes and functions to handle and validate the contents of the config file
"""

__autor__ = "Leon Eiböck"
__date__ = "15/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from pathlib import Path
import yaml


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
            raise TypeError
        if not Path(path).exists():
            raise FileNotFoundError()
        self.path = Path(path)

    def read_file(self) -> dict:
        """
        Reads the contents of the YAML-file
        :return: The contents of the YAML-file as a dictionary

        >>> config = ConfigFileHandler("./config_file_example.yml")
        >>> config.read_file().keys()
        dict_keys(['nodes', 'edges'])
        """
        with open(self.path, "r") as file:
            return yaml.safe_load(file)

    def validate_file(self) -> None:
        """
        Validates the contents of the YAML-file as defined
        :return:
        >>> config = ConfigFileHandler("./config_file_example.yml")
        >>> config.validate_file()

        #TODO make UNIT tests
        """
        content = self.read_file()
        if not {"edges", "nodes"} <= content.keys():
            raise KeyError

        self.nodes = content["nodes"]
        self.edges = content["edges"]

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
        if not {"image", "role", "names"} <= node_group.keys():
            raise KeyError
        if node_group["role"] not in self.__VALID_ROLES:
            raise ValueError

        names = node_group["names"]
        if names is None:
            return
        if not len(names) == len(set(names)):
            raise ValueError
        if set(names) & self.__NODE_NAMES:
            raise ValueError
        self.__NODE_NAMES.update(names)

    def __validate_edges(self, edge: list) -> None:
        """
        Helper-methode for validate_file. Validates the entries of given edge.
        :param edge: List entry of edges. Contains the connections between the nodes.
        :return:
        #TODO make UNIT tests
        """
        if len(edge) != 4:
            raise ValueError
        if not {edge[0], edge[2]} <= self.__NODE_NAMES:
            raise ValueError
        # TODO validate Interfaces, if ip-Address and option is set
