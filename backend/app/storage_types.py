"""Exact numeric storage: PostgreSQL NUMERIC, scaled integers in local SQLite."""

from datetime import UTC
from decimal import Decimal, InvalidOperation

from sqlalchemy import BigInteger, DateTime, Numeric, Text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import sum as SqlSum
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """SQLite stores UTC without an offset; expose aware timestamps in both engines."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and dialect.name == "sqlite" and value.tzinfo is not None:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class ExactNumeric(TypeDecorator):
    impl = Numeric
    cache_ok = True

    def __init__(self, precision, scale):
        self.precision = precision
        self.scale = scale
        super().__init__(precision=precision, scale=scale)

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(BigInteger() if self.scale == 4 else Text())
        return dialect.type_descriptor(Numeric(self.precision, self.scale))

    def process_bind_param(self, value, dialect):
        if value is None or dialect.name != "sqlite":
            return value
        try:
            number = Decimal(str(value))
            if not number.is_finite() or abs(number) >= Decimal(10) ** (
                self.precision - self.scale
            ):
                raise ValueError("Numeric value exceeds its declared precision")
            quantized = number.quantize(Decimal(10) ** -self.scale)
            if quantized != number:
                raise ValueError("Numeric value exceeds its declared scale")
            return int(quantized * 10000) if self.scale == 4 else format(quantized, "f")
        except InvalidOperation:
            raise ValueError("Invalid exact numeric value") from None

    def process_result_value(self, value, dialect):
        if value is None or dialect.name != "sqlite":
            return value
        number = Decimal(str(value))
        return number.scaleb(-4) if self.scale == 4 else number


@compiles(SqlSum, "sqlite")
def exact_sqlite_sum(element, compiler, **kwargs):
    # SUM over money must not overflow SQLite's signed 64-bit aggregate or use float.
    argument = next(iter(element.clauses), None)
    if (
        argument is not None
        and isinstance(argument.type, ExactNumeric)
        and argument.type.scale == 4
    ):
        return f"local_sum_money({compiler.process(argument, **kwargs)})"
    return compiler.visit_function(element, **kwargs)
