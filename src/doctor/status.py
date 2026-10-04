from __future__ import annotations

from enum import Enum


class Status:
    """
    Object to save a status.
    """

    class StatusEnum(Enum):
        """
        Enum class for the states.
        """

        OK = "OK"
        ERROR = "ERROR"
        EXISTS = "EXISTS"
        MISSING = "MISSING"
        FAULT = "FAULT"
        INFO = "INFO"

    def __init__(self, status: StatusEnum, message: str):
        """
        :param status: Status of the status object.
        :param message: Message of the status object.
        """
        self.__status = status
        self.__message = message

    def __repr__(self) -> str:
        max_length = 0
        for status in Status.StatusEnum:
            max_length = max(max_length, len(str(status.value)))
        colors = self.get_status_color()
        status_field = f"<{colors[0]}{self.__status.name:<{max_length}}{colors[1]}>"
        return f"Status{status_field} | {colors[0]}{self.__message}{colors[1]}"

    def get_status_color(self) -> tuple[str, str]:
        """
        Returns the colour of the state.
        :return: Returns a tuple with the start and end sequence of the colour
        """
        match self.__status:
            case self.StatusEnum.OK:
                return "\033[32m", "\033[0m"  # Green
            case self.StatusEnum.ERROR:
                return "\033[31m", "\033[0m"  # Red
            case self.StatusEnum.EXISTS:
                return "\033[32m", "\033[0m"  # Green
            case self.StatusEnum.MISSING:
                return "\033[31m", "\033[0m"  # Red
            case self.StatusEnum.FAULT:
                return "\033[31m", "\033[0m"  # Red
            case self.StatusEnum.INFO:
                return "\033[34m", "\033[0m"  # Blue

    @property
    def status(self) -> StatusEnum:
        """Status of the status object."""
        return self.__status

    @property
    def message(self) -> str:
        """Message of the status object."""
        return self.__message

    @staticmethod
    def ok(msg: str) -> Status:
        """
        Creates a Status object with an OK status and given message.
        :param msg: Message to create Status object with.
        :return: Returns the created Status object.
        """
        return Status(Status.StatusEnum.OK, msg)

    @staticmethod
    def info(msg: str) -> Status:
        """
        Creates a Status object with an INFO status and given message.
        :param msg: Message to create Status object with.
        :return: Returns the created Status object.
        """
        return Status(Status.StatusEnum.INFO, msg)

    @staticmethod
    def fault(msg: str) -> Status:
        """
        Creates a Status object with an FAULT status and given message.
        :param msg: Message to create Status object with.
        :return: Returns the created Status object.
        """
        return Status(Status.StatusEnum.FAULT, msg)

    @staticmethod
    def error(msg: str) -> Status:
        """
        Creates a Status object with an ERROR status and given message.
        :param msg: Message to create Status object with.
        :return: Returns the created Status object.
        """
        return Status(Status.StatusEnum.ERROR, msg)

    @staticmethod
    def exists(msg: str) -> Status:
        """
        Creates a Status object with an EXISTS status and given message.
        :param msg: Message to create Status object with.
        :return: Returns the created Status object.
        """
        return Status(Status.StatusEnum.EXISTS, msg)

    @staticmethod
    def missing(msg: str) -> Status:
        """
        Creates a Status object with an MISSING status and given message.
        :param msg: Message to create Status object with.
        :return: Returns the created Status object.
        """
        return Status(Status.StatusEnum.MISSING, msg)
