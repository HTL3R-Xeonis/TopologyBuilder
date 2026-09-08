import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from loguru import logger

from .verbosity import Verbosity

load_dotenv()


def check_value_type[T](value: Any, value_type: type[T] | tuple[type[T], ...]) -> T:
    """
    Checks given value type and returns the value.
    :param value: Value to check.
    :param value_type: Value type which value can have.
    :return: Returns the value.
    :raises ValueError: Is thrown when the value is not of the corresponding type.
    """
    if not isinstance(value, value_type):
        logger.error(
            msg
            := f"Setting value {value} is of wrong type {type(value)}. Should be of type {value_type}."
        )
        raise TypeError(msg)
    return value


class Settings:
    @staticmethod
    def reset_settings() -> None:
        """
        Removes the custom settings. Default settings takes over.
        :return:
        """
        Settings.initialise_settings()

    @staticmethod
    def is_fully_initialised(cls_object: Any, class_path="") -> bool:
        """
        Checks recursively whether the class attributes are all initialized, meaning not None.
        :param cls_object: Class to check.
        :param class_path: Classpath of the nested class.
        :return: True if all attributes are initialized, False otherwise.
        """
        is_it = True
        class_path = f"{class_path}.{cls_object.__name__}".lstrip(".")
        for key, value in vars(cls_object).items():
            if key.startswith("_"):
                continue

            if isinstance(value, type):
                is_it = is_it & Settings.is_fully_initialised(value, class_path)
                continue

            if value is None and key.lower() != "password":
                logger.warning(f"{class_path}.{key} is None. May lead to errors.")

        return is_it

    @staticmethod
    def initialise_settings(
        *,
        default_settings: Path = Path("./default_settings.yaml"),
        custom_settings: Path | None = None,
    ) -> None:
        """
        Initializes the default settings and if not None, the custom settings as well.
        :param default_settings: Path to the default YAML settings file.
        :param custom_settings: Path to the custom YAML settings file. Set ``None`` to just use default settings.
        :return:
        """
        if not (
            default_settings.name.endswith(".yaml")
            or default_settings.name.endswith(".yml")
        ):
            logger.error(msg := "Default settings file is not a yaml file.")
            raise ValueError(msg)
        if not default_settings.exists():
            logger.error(
                msg
                := f"Path to default settings file does not exist: {default_settings}"
            )
            raise ValueError(msg)
        if not default_settings.is_file():
            logger.error(msg := "Default settings file is not a file.")
            raise ValueError(msg)
        Settings.initialise_settings_file(default_settings)

        if custom_settings is None:
            Settings.is_fully_initialised(Settings)
            return
        if not (
            custom_settings.name.endswith(".yaml")
            or custom_settings.name.endswith(".yml")
        ):
            logger.error(msg := "Custom settings file is not a yaml file.")
            raise ValueError(msg)
        if not custom_settings.exists():
            logger.error(
                msg
                := f"Path to custom settings file does not exist: {default_settings}"
            )
            raise ValueError(msg)
        if not custom_settings.is_file():
            logger.error(msg := "Custom settings file is not a file.")
            raise ValueError(msg)
        Settings.initialise_settings_file(custom_settings)

        Settings.is_fully_initialised(Settings)

    @staticmethod
    def initialise_settings_file(path: Path) -> None:
        """
        Initializes the settings based on a YAML file.
        :param path: Path to the YAML file.
        :return:
        :raises ValueError: Is thrown when the value of a setting option is not correct.
        """
        with open(path, "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)

        for key, value in config.items():
            match key:
                case "verbosity_level":
                    verbosity = Verbosity.get_verbosity_equivalent(
                        check_value_type(value, str)
                    )

                    if verbosity is not None:
                        Settings.VERBOSITY_LEVEL = verbosity
                        continue
                    logger.warning(
                        f"Unrecognized verbosity value {key}. "
                        f"Possible values are: {[v.value for v in Verbosity]}. "
                        f"Value will be set to NORMAL."
                    )
                    Settings.VERBOSITY_LEVEL = Verbosity.NORMAL

                case "topology_file":
                    Settings.TOPOLOGY_FILE = check_value_type(value, str)
                case "is_dry_run":
                    Settings.IS_DRY_RUN = check_value_type(value, bool)
                case "esxi":
                    Settings._initialise_esxi_settings(check_value_type(value, dict))
                case "gns3":
                    Settings._initialise_gns3_settings(check_value_type(value, dict))
                case "api":
                    Settings._initialise_api_settings(check_value_type(value, dict))
                case _:
                    logger.warning(f"Unrecognized setting: Settings.{key.upper()}")

    @staticmethod
    def _initialise_esxi_settings(esxi_settings: dict) -> None:
        """
        Initializes the ESXi part of the settings.
        :param esxi_settings: ``esxi`` value of the settings file.
        :return:
        :raises ValueError: Is thrown when the value of a setting option is not correct.
        """
        for key, value in esxi_settings.items():
            match key:
                case "ip":
                    Settings.ESXI.IP = check_value_type(value, str)
                case "port":
                    Settings.ESXI.PORT = check_value_type(value, int)
                case "username":
                    Settings.ESXI.USERNAME = check_value_type(value, str)
                case "password":
                    if value is None:
                        value = os.getenv("ESXI_PASSWORD", None)
                    if value is None:
                        value = input("Enter ESXI password: ")
                    if value == "":
                        value = None
                    Settings.ESXI.PASSWORD = check_value_type(value, (str, type(None)))
                case "virtual_switch":
                    Settings.ESXI.VIRTUAL_SWITCH = check_value_type(value, str)
                case "trunk_port_group":
                    Settings.ESXI.TRUNK_PORT_GROUP = check_value_type(value, str)
                case "management_port_group":
                    Settings.ESXI.MANAGEMENT_PORT_GROUP = check_value_type(value, str)
                case "ignore_virtual_switches":
                    Settings.ESXI.IGNORE_VIRTUAL_SWITCHES = set(
                        check_value_type(value, (set, list))
                    )
                case "ignore_port_groups":
                    Settings.ESXI.IGNORE_PORT_GROUPS = set(
                        check_value_type(value, (set, list))
                    )
                case "ignore_virtual_machines":
                    Settings.ESXI.IGNORE_VIRTUAL_MACHINES = set(
                        check_value_type(value, (set, list))
                    )
                case "ignore_port_groups":
                    Settings.ESXI.IGNORE_PORT_GROUPS = set(
                        check_value_type(value, (list, set))
                    )
                case "datastore":
                    Settings.ESXI.DATASTORE = check_value_type(value, str)
                case "gns3_vm_name":
                    Settings.ESXI.GNS3_VM_NAME = check_value_type(value, str)
                case _:
                    logger.warning(f"Unrecognized setting: Settings.ESXI.{key.upper()}")

    @staticmethod
    def _initialise_gns3_settings(gns3_settings: dict) -> None:
        """
        Initializes the GNS3 part of the settings.
        :param gns3_settings: ``gns3`` value of the settings file.
        :return:
        :raises ValueError: Is thrown when the value of a setting option is not correct.
        """
        for key, value in gns3_settings.items():
            match key:
                case "username":
                    Settings.GNS3.USERNAME = check_value_type(value, str)
                case "password":
                    if value is None:
                        value = os.getenv("GNS3_PASSWORD", None)
                    if value is None:
                        value = input("Enter GNS3 password: ")
                    if value == "":
                        value = None
                    Settings.GNS3.PASSWORD = check_value_type(value, (str, type(None)))
                case "project_name":
                    Settings.GNS3.PROJECT_NAME = check_value_type(value, str)
                case "port":
                    Settings.GNS3.PORT = check_value_type(value, int)
                case "parent_interface":
                    Settings.GNS3.PARENT_INTERFACE = check_value_type(value, str)
                case _:
                    logger.warning(f"Unrecognized setting: Settings.GNS3.{key.upper()}")

    @staticmethod
    def _initialise_api_settings(api_settings: dict) -> None:
        """
        Initializes the API part of the settings.
        :param api_settings: ``api`` value of the settings file.
        :return:
        :raises ValueError: Is thrown when the value of a setting option is not correct.
        """
        for key, value in api_settings.items():
            match key:
                case "gns3_template_server_url":
                    Settings.API.GNS3_TEMPLATE_SERVER_URL = check_value_type(value, str)
                case "esxi_template_server_url":
                    Settings.API.ESXI_TEMPLATE_SERVER_URL = check_value_type(value, str)
                case "literal_api_values":
                    if value is None:
                        value = (
                            os.getenv("LITERAL_API_VALUES", "false").lower() == "true"
                        )
                    Settings.API.LITERAL_API_VALUES = check_value_type(value, bool)
                case "literal_esxi_templates":
                    Settings.API.LITERAL_ESXI_TEMPLATES = set(
                        check_value_type(value, (list, set))
                    )
                case "literal_gns3_templates":
                    Settings.API.LITERAL_GNS3_TEMPLATES = set(
                        check_value_type(value, (list, set))
                    )
                case _:
                    logger.warning(f"Unrecognized setting: Settings.API.{key.upper()}")

    # ------------------------ Setting Attributes ------------------------

    VERBOSITY_LEVEL: Verbosity = None
    """The verbosity level of the program."""
    TOPOLOGY_FILE: str = None
    """Path to the YAML file which represents the topology."""
    IS_DRY_RUN: bool = None
    """If True, only prints what would happen. May still execute API requests."""

    class ESXI:
        """Settings related to ESXi."""

        IP: str = None
        """IPv4 address of the ESXi client."""
        PORT: int = None
        """Port of the ESXi client, where the API requests are expected."""
        USERNAME: str = None
        """Username to use for the ESXi connections."""
        PASSWORD: str | None = None
        """Password to use for the ESXi connections."""
        VIRTUAL_SWITCH: str = None
        """Specifies the virtual switch to use on the ESXi client."""
        TRUNK_PORT_GROUP: str = None
        """Specifies which port group should be used for the GNS3 VM to have a connection to every other VM on the ESXi host."""
        MANAGEMENT_PORT_GROUP: str = None
        """Specifies which port group should be used for the management of the GNS3 VM. This portgroup should be on a separate virtual switch, which must have a physical adapter."""
        IGNORE_VIRTUAL_SWITCHES: set[str] = None
        """Specifies which virtual switches not to edit."""
        IGNORE_PORT_GROUPS: set[str] = None
        """Specifies which port groups not to edit."""
        IGNORE_VIRTUAL_MACHINES: set[str] = None
        """Specifies which virtual machines not to edit"""
        DATASTORE: str = None
        """Specifies the name of the datastore to use on the ESXi client."""
        GNS3_VM_NAME: str = None
        """Name of the GNS3 VM to work on."""

    class GNS3:
        """Settings related to GNS3."""

        USERNAME: str = None
        """Username to use for the GNS3 connections."""
        PASSWORD: str | None = None
        """Password to use for the GNS3 connections."""
        PROJECT_NAME: str = None
        """Name of the GNS3 project to work on. If this project already exists on the GNS3 server, it is going to be overwritten."""
        PORT: int = None
        """Port of the GNS3 client, where the API requests are expected."""
        PARENT_INTERFACE: str = None
        """Name of the interface of the GNS3 VM to create and delete the subinterfaces."""

    class API:
        """Settings related to API requests."""

        GNS3_TEMPLATE_SERVER_URL: str = None
        """URL to the GNS3 template API server."""
        ESXI_TEMPLATE_SERVER_URL: str = None
        """URL to the ESXi template API server."""
        LITERAL_API_VALUES: bool = None
        """Specifies whether to use literal API values instead of using API calls to get the existing templates."""
        LITERAL_ESXI_TEMPLATES: set[str] = None
        """Literal ESXi template name values."""
        LITERAL_GNS3_TEMPLATES: set[str] = None
        """Literal GNS3 template name values."""
