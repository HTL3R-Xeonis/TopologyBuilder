from __future__ import annotations

from enum import Enum
from functools import total_ordering


class StatusList:
    """Collects and displays health-check results."""

    def __init__(self) -> None:
        """Creates an empty result collection."""
        self._items: set[Status] = set()

    def add(self, status: Status) -> None:
        """Adds a result."""
        self._items.add(status)

    def extend(self, statuses: StatusList) -> None:
        """Adds results from another collection."""
        self._items.update(statuses._items)

    def __iter__(self):
        """Returns results ordered by topic and severity."""
        return iter(sorted(self._items))

    def __len__(self) -> int:
        """Returns the number of results."""
        return len(self._items)

    @property
    def has_failures(self) -> bool:
        """Indicates whether a check reported a problem."""
        return any(item.status in Status.FAILURE_STATES for item in self._items)

    def __repr__(self) -> str:
        """Returns the formatted results."""
        width = max((len(item.topic) for item in self._items), default=0)
        return "\n".join(f"{item.topic:<{width}} - {item!r}" for item in self)


@total_ordering
class Status:
    """Describes a single health-check result."""

    class StatusEnum(Enum):
        OK = "OK"
        ERROR = "ERROR"
        EXISTS = "EXISTS"
        MISSING = "MISSING"
        FAULT = "FAULT"
        INFO = "INFO"

    FAILURE_STATES = frozenset({StatusEnum.ERROR, StatusEnum.MISSING, StatusEnum.FAULT})

    def __init__(self, status: StatusEnum, topic: str, message: str):
        """Creates a check result."""
        self._status = status
        self._topic = topic
        self._message = message

    @property
    def status(self) -> StatusEnum:
        """Returns the result state."""
        return self._status

    @property
    def topic(self) -> str:
        """Returns the result category."""
        return self._topic

    @property
    def message(self) -> str:
        """Returns the result description."""
        return self._message

    def __repr__(self) -> str:
        """Returns a colored check result."""
        color, reset = self.get_status_color(self)
        return f"{color}[{self._status.value}] {self._message}{reset}"

    def __eq__(self, other):
        """Compares two check results."""
        if not isinstance(other, Status):
            return NotImplemented
        return (self.topic, self.status, self.message) == (other.topic, other.status, other.message)

    def __hash__(self):
        """Returns a stable hash for a check result."""
        return hash((self.topic, self.status, self.message))

    def __lt__(self, other):
        """Orders check results for display."""
        if not isinstance(other, Status):
            return NotImplemented
        return (self.topic, self.status.value, self.message) < (other.topic, other.status.value, other.message)

    @staticmethod
    def get_status_color(status: Status) -> tuple[str, str]:
        """Returns the terminal color for a result."""
        color = (
            "\033[31m"
            if status.status in Status.FAILURE_STATES
            else "\033[34m"
            if status.status == Status.StatusEnum.INFO
            else "\033[32m"
        )
        return color, "\033[0m"

    @staticmethod
    def ok(topic: str, msg: str) -> Status:
        """Creates a successful result."""
        return Status(Status.StatusEnum.OK, topic, msg)

    @staticmethod
    def info(topic: str, msg: str) -> Status:
        """Creates an informational result."""
        return Status(Status.StatusEnum.INFO, topic, msg)

    @staticmethod
    def fault(topic: str, msg: str) -> Status:
        """Creates a failed result."""
        return Status(Status.StatusEnum.FAULT, topic, msg)

    @staticmethod
    def error(topic: str, msg: str) -> Status:
        """Creates an error result."""
        return Status(Status.StatusEnum.ERROR, topic, msg)

    @staticmethod
    def exists(topic: str, msg: str) -> Status:
        """Creates a resource-present result."""
        return Status(Status.StatusEnum.EXISTS, topic, msg)

    @staticmethod
    def missing(topic: str, msg: str) -> Status:
        """Creates a resource-missing result."""
        return Status(Status.StatusEnum.MISSING, topic, msg)
