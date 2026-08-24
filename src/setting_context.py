from typing import Callable, Generic, TypeVar
from src.settings import Settings
import inspect

T = TypeVar("T")
C = TypeVar("C")


class ClassProperty(Generic[C, T]):
    def __init__(self, func: Callable[[C], T]):
        self.func = func

    def __get__(self, instance, owner) -> T:
        return self.func(owner)


class ObjectContext:
    _instances: dict[object, ObjectContext] = {}

    def __new__(cls, *args, **kwargs):
        graph = kwargs.get("obj")
        if graph not in cls._instances:
            cls._instances[graph] = super().__new__(cls)
        return cls._instances[graph]

    def __init__(self, *, obj: object, settings: Settings):
        self._settings = settings

    @ClassProperty
    def settings(self) -> Settings:
        obj = self._inspect_stack()
        return self._instances[obj]._settings

    @staticmethod
    def _inspect_stack():
        frame = inspect.currentframe()
        if frame is None:
            raise RuntimeError("Stack is empty")
        try:
            while frame := frame.f_back:
                obj = frame.f_locals.get("self")
                if obj in ObjectContext._instances:
                    return obj
            return None
        finally:
            del frame
