"""
Picks a MAC address from an administrator-configured range - e.g. so a
DHCP server can be set up to only hand out IP addresses to devices whose
MAC falls within that range. See Settings.ESXI.GNS3_VM_MAC_RANGE and
gns3_vm_deploy.deploy_fresh_gns3_vm, its only caller today.
"""

from __future__ import annotations

import random

_MAC_RANGE_PICK_ATTEMPTS = 200


def mac_to_int(mac: str) -> int:
    """
    :param mac: a MAC address as six colon-separated hex octets, e.g. "00:50:56:00:10:2a"
    :return: the MAC as a 48-bit integer
    :raises ValueError: if mac isn't a well-formed MAC address string
    """
    parts = mac.split(":")
    if len(parts) != 6 or not all(len(p) == 2 for p in parts):
        raise ValueError(
            f"'{mac}' is not a valid MAC address (expected six colon-separated hex octets)"
        )
    try:
        return int("".join(parts), 16)
    except ValueError:
        raise ValueError(
            f"'{mac}' is not a valid MAC address (expected six colon-separated hex octets)"
        ) from None


def int_to_mac(value: int) -> str:
    """
    :param value: a 48-bit integer
    :return: value formatted as a MAC address, e.g. "00:50:56:00:10:2a"
    """
    hex_str = f"{value:012x}"
    return ":".join(hex_str[i : i + 2] for i in range(0, 12, 2))


def mac_in_range(mac: str, start: str, end: str) -> bool:
    """:return: whether mac falls within the inclusive [start, end] range."""
    return mac_to_int(start) <= mac_to_int(mac) <= mac_to_int(end)


def pick_mac_in_range(start: str, end: str, excluded: set[str] = frozenset()) -> str:
    """
    Picks a random MAC address within the inclusive [start, end] range,
    avoiding anything in ``excluded``.
    :param start: first MAC address in the range (inclusive)
    :param end: last MAC address in the range (inclusive)
    :param excluded: MAC addresses (e.g. already in use by other VMs on
        the host) never to pick
    :return: a MAC address string within the range
    :raises ValueError: if start is after end, or no free MAC could be
        found within _MAC_RANGE_PICK_ATTEMPTS random attempts (an
        exhausted or near-exhausted range - widen it, since an almost-
        full range isn't guaranteed to succeed on every attempt anyway)
    """
    start_int = mac_to_int(start)
    end_int = mac_to_int(end)
    if start_int > end_int:
        raise ValueError(f"MAC range start '{start}' is after end '{end}'")

    excluded_ints = {mac_to_int(mac) for mac in excluded if mac}

    for _ in range(_MAC_RANGE_PICK_ATTEMPTS):
        candidate = random.randint(start_int, end_int)
        if candidate not in excluded_ints:
            return int_to_mac(candidate)

    raise ValueError(
        f"Could not find a free MAC address in range {start}-{end} after "
        f"{_MAC_RANGE_PICK_ATTEMPTS} attempts - the range may be full"
    )
