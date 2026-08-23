from typing import Any


def nested_formatter(header: str, obj: str | None | list[Any] | Any) -> str:
    if obj is None:
        return "None"
    if isinstance(obj, str):
        return "\n" + "\n".join(
            [" " * len(header) + "  " + part for part in obj.split("\n")]
        )
    if isinstance(obj, list):
        return "\n".join([nested_formatter(header, intf) for intf in obj]).lstrip(" ")

    return nested_formatter(header, repr(obj))
