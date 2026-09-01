from enum import Enum


class Verbosity(str, Enum):
    """
    Verbosity enum.
    """

    QUIET = "q"
    NORMAL = "n"
    VERBOSE = "v"
    DEBUG = "d"

    @property
    def level(self) -> int:
        """
        Get verbosity level of current verbosity.
        :return:
        """
        return {
            Verbosity.QUIET.value: 0,
            Verbosity.NORMAL.value: 1,
            Verbosity.VERBOSE.value: 2,
            Verbosity.DEBUG.value: 3,
        }[self.value]

    @staticmethod
    def volumatic_print(verbosity: Verbosity, msg: str) -> None:
        """
        Print message if verbosity level is higher or equal to verbosity level.
        :param verbosity: Minimal verbosity level where the message is printed.
        :param msg: Message to be printed.
        :return:
        """
        from .settings import Settings

        if Settings.VERBOSITY_LEVEL.level >= verbosity.level:
            print(msg)
