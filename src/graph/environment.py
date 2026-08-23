from enum import Enum
from functools import lru_cache
from typing import Tuple, Literal

from src.connections import APIHandler


class Environment(Enum):
    """
    Enum class to represent the environment on which the node with a certain image is.
    """

    ON_NOTHING = 0
    ON_ESXI = 1
    ON_GNS3 = 2

    @staticmethod
    @lru_cache(maxsize=1)
    def _get_templates() -> Tuple[frozenset, frozenset]:
        """
        Returns a tuple Frozen-sets with the available template names on GNS3 and ESXi
        :return: Tupel with two Frozen-sets. First index is for GNS3, second is for ESXi
        """
        gns3_templates = frozenset(APIHandler.get_gns3_template_names())
        esxi_templates = frozenset(APIHandler.get_esxi_template_names())
        return gns3_templates, esxi_templates

    @staticmethod
    def get_environment(
        image: str,
    ) -> Literal[Environment.ON_GNS3, Environment.ON_ESXI, Environment.ON_NOTHING]:
        """
        Returns the environment based on the image
        #@TODO add description and tests
        :param image: image to judge the environment on
        :return: Either returns ON_ESXI or ON_GNS3. When the template-name isn't on either then it returns ON_NOTHING
        """
        if image in Environment._get_templates()[0]:
            return Environment.ON_GNS3
        if image in Environment._get_templates()[1]:
            return Environment.ON_ESXI
        return Environment.ON_NOTHING
