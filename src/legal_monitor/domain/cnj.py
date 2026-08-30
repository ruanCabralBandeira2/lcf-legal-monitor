from __future__ import annotations

import re
from dataclasses import dataclass

CNJ_FORMAT = re.compile(
    r"^(?P<sequence>\d{7})-?(?P<check>\d{2})\.?(?P<year>\d{4})\.?(?P<justice>\d)\.?(?P<tribunal>\d{2})\.?(?P<origin>\d{4})$"
)


class InvalidCnjNumber(ValueError):
    """Número CNJ com formato ou dígito verificador inválido."""


@dataclass(frozen=True, slots=True, order=True)
class CnjNumber:
    digits: str

    def __post_init__(self) -> None:
        if not self.digits.isdigit() or len(self.digits) != 20:
            raise InvalidCnjNumber("O número CNJ deve conter exatamente 20 dígitos")
        if self.modulo_97_payload % 97 != 1:
            raise InvalidCnjNumber("Dígitos verificadores CNJ inválidos")

    @classmethod
    def parse(cls, value: str) -> CnjNumber:
        match = CNJ_FORMAT.fullmatch(value.strip())
        if not match:
            raise InvalidCnjNumber("Formato esperado: NNNNNNN-DD.AAAA.J.TR.OOOO")
        groups = match.groupdict()
        digits = (
            groups["sequence"]
            + groups["check"]
            + groups["year"]
            + groups["justice"]
            + groups["tribunal"]
            + groups["origin"]
        )
        return cls(digits)

    @classmethod
    def from_components(
        cls,
        *,
        sequence: int,
        year: int,
        justice: int,
        tribunal: int,
        origin: int,
    ) -> CnjNumber:
        base = f"{sequence:07d}{year:04d}{justice:d}{tribunal:02d}{origin:04d}"
        check = 98 - (int(base + "00") % 97)
        return cls.parse(
            f"{sequence:07d}-{check:02d}.{year:04d}.{justice:d}.{tribunal:02d}.{origin:04d}"
        )

    @property
    def modulo_97_payload(self) -> int:
        sequence = self.digits[0:7]
        check = self.digits[7:9]
        year = self.digits[9:13]
        justice = self.digits[13]
        tribunal = self.digits[14:16]
        origin = self.digits[16:20]
        return int(sequence + year + justice + tribunal + origin + check)

    @property
    def year(self) -> int:
        return int(self.digits[9:13])

    @property
    def tribunal_code(self) -> str:
        return self.digits[14:16]

    def masked(self) -> str:
        return f"*******-**.{self.digits[9:13]}.*.**.****"

    def __str__(self) -> str:
        d = self.digits
        return f"{d[0:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:20]}"
