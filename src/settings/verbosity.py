from enum import Enum


class Verbosity(str, Enum):
    QUIET = "q"
    NORMAL = "n"
    VERBOSE = "v"
    DEBUG = "d"

    @property
    def level(self) -> int:
        return {
            Verbosity.QUIET.value: 0,
            Verbosity.NORMAL.value: 1,
            Verbosity.VERBOSE.value: 2,
            Verbosity.DEBUG.value: 3,
        }[self.value]

    @staticmethod
    def volumatic_print(verbosity: Verbosity, msg: str) -> None:
        from .settings import Settings

        if Settings.VERBOSITY_LEVEL.level >= verbosity.level:
            print(msg)
