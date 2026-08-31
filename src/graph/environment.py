from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Tuple, Literal

from src.connections.api_handler import APIHandler


def normalize_template_name(name: str) -> str:
    """
    Normalizes a template/image name for lenient comparison: case-insensitive,
    with ALL whitespace removed (not just collapsed) - real-world template
    names have been observed to disagree with a topology config's image name
    on whether a space exists at a given position at all, not just how many
    (e.g. "Cisco IOSv 15.6(1)T" vs "Cisco IOSv 15.6(1) T"), so collapsing
    whitespace runs to a single space still wouldn't make those equal.
    :param name: the name to normalize
    :return: normalized name, safe to compare with ==
    """
    return "".join(name.split()).lower()


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
        Returns the environment based on the image. Matching ignores case and
        whitespace differences (see normalize_template_name).
        :param image: image to judge the environment on
        :return: Either returns ON_ESXI or ON_GNS3. When the template-name isn't on either then it returns ON_NOTHING
        """
        normalized_image = normalize_template_name(image)
        gns3_templates, esxi_templates = Environment._get_templates()
        if any(normalize_template_name(t) == normalized_image for t in gns3_templates):
            return Environment.ON_GNS3
        if any(normalize_template_name(t) == normalized_image for t in esxi_templates):
            return Environment.ON_ESXI
        return Environment.ON_NOTHING
