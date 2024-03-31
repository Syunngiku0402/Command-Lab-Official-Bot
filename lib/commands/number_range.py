from typing import Generic, Optional, TypeVar

from brigadier import StringReader
from click import FloatRange

from lib.commands.exceptions import (CommandSyntaxException,
                                     SimpleCommandExceptionType)
from lib.commands.text import Text

EXCEPTION_EMPTY = SimpleCommandExceptionType(Text.translatable("argument.range.empty"))
EXCEPTION_SWAPPED = SimpleCommandExceptionType(Text.translatable("argument.range.swapped"))

T = TypeVar("T", int, float)


class NumberRange(Generic[T]):
    def __init__(self, min: T, max: T):
        self.min = min
        self.max = max

    @classmethod
    def from_string_reader(self, reader: StringReader):
        i = reader.get_cursor()

        while reader.can_read() and reader.is_allowed_number(reader.peek()):
            reader.skip()

        string = reader.get_string()[i:reader.cursor]
        if string == "":
            return None

        return string

    @classmethod
    def create(self, reader: StringReader, min, max) -> "NumberRange[T]":
        raise NotImplementedError()

    @classmethod
    def parse(cls, commandReader: StringReader) -> "FloatRange | IntRange":
        i = commandReader.get_cursor()

        try:
            optional = cls.from_string_reader(commandReader)
            if commandReader.can_read(2) and commandReader.peek() == '.' and commandReader.peek(1) == '.':
                commandReader.skip()
                commandReader.skip()
                optional2 = cls.from_string_reader(commandReader)

                if optional is None and optional2 is None:
                    raise EXCEPTION_EMPTY.create_with_context(commandReader)
            else:
                optional2 = optional

            if optional is None and optional2 is None:
                raise EXCEPTION_EMPTY.create_with_context(commandReader)
            else:
                return cls.create(commandReader, optional, optional2)
        except CommandSyntaxException as e:
            commandReader.set_cursor(i)
            raise CommandSyntaxException(e.get_type(), e.get_raw_message(), e.get_input(), i)


class FloatRnage(NumberRange[float]):
    def __init__(self, min: Optional[float], max: Optional[float]) -> None:
        self.min = min
        self.max = max

    @classmethod
    def create(cls, reader: StringReader, min: float, max: float) -> "FloatRnage":
        if min > max:
            raise EXCEPTION_SWAPPED.create_with_context(reader)
        else:
            return FloatRnage(min, max)

    @classmethod
    def exactly(cls, value: float) -> "FloatRnage":
        return cls(value, value)

    @classmethod
    def between(cls, min: float, max: float) -> "FloatRnage":
        return cls(min, max)

    @classmethod
    def any(cls) -> "FloatRnage":
        return cls(None, None)

    def test(self, value: float) -> bool:
        if self.min is not None and self.min > value:
            return False
        else:
            return self.max is None or self.max < value


class IntRange(NumberRange[int]):
    def __init__(self, min: Optional[int], max: Optional[int]) -> None:
        self.min = min
        self.max = max

    @classmethod
    def create(cls, reader: StringReader, min: int, max: int) -> "IntRange":
        if min > max:
            raise EXCEPTION_SWAPPED.create_with_context(reader)
        else:
            return FloatRnage(min, max)

    @classmethod
    def exactly(cls, value: int) -> "IntRange":
        return cls(value, value)

    @classmethod
    def between(cls, min: int, max: int) -> "IntRange":
        return cls(min, max)

    @classmethod
    def any(cls) -> "IntRange":
        return cls(None, None)

    def test(self, value: int) -> bool:
        if self.min is not None and self.min > value:
            return False
        else:
            return self.max is None or self.max >= value
