"""Leitura da carteira de processos (ex.: lista exportada do Astrea) e separação por site.

Formato: um número por linha; opcionalmente `;RESTRICTED` (família, criminal, segredo).
Linhas vazias ou iniciadas por `#` são ignoradas. O arquivo fica fora do Git
(`storage/carteira/`), pois contém números processuais reais.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from legal_monitor.connectors.routing import CATALOG, candidate_keys, tribunal_for
from legal_monitor.domain.cnj import CnjNumber, InvalidCnjNumber
from legal_monitor.domain.enums import Sensitivity

# Aceita "NNNNNNN-DD.AAAA.J.TR.OOOO" e a variante com ponto no lugar do hífen.
CNJ_IN_TEXT = re.compile(r"(?<!\d)(\d{7})[-.](\d{2})\.(\d{4})\.(\d)\.(\d{2})\.(\d{4})(?!\d)")
SITE_FLAG = re.compile(r"SITE=([a-z0-9-]+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PortfolioEntry:
    cnj: CnjNumber
    sensitivity: Sensitivity
    tribunal: str | None
    # `;SITE=<chave>` força o site (ex.: processo em recurso no tribunal com número da vara).
    site_override: str | None = None

    @property
    def likely_site(self) -> str:
        if self.site_override:
            return self.site_override
        return candidate_keys(self.cnj)[0] if self.tribunal else "sem-robo"


@dataclass
class Portfolio:
    entries: list[PortfolioEntry] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    not_cnj: list[str] = field(default_factory=list)
    duplicates: int = 0

    def by_site(self) -> dict[str, list[PortfolioEntry]]:
        groups: dict[str, list[PortfolioEntry]] = defaultdict(list)
        for entry in self.entries:
            groups[entry.likely_site].append(entry)
        return dict(sorted(groups.items(), key=lambda item: -len(item[1])))


def parse_portfolio(text: str) -> Portfolio:
    portfolio = Portfolio()
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        number, _, flags = line.partition(";")
        match = CNJ_IN_TEXT.search(number)
        if not match:
            portfolio.not_cnj.append(number.strip())
            continue
        formatted = "{}-{}.{}.{}.{}.{}".format(*match.groups())
        try:
            cnj = CnjNumber.parse(formatted)
        except InvalidCnjNumber:
            portfolio.invalid.append(formatted)
            continue
        if cnj.digits in seen:
            portfolio.duplicates += 1
            continue
        seen.add(cnj.digits)
        sensitivity = (
            Sensitivity.RESTRICTED if "RESTRICTED" in flags.upper() else Sensitivity.CONFIDENTIAL
        )
        site = SITE_FLAG.search(flags)
        site_key = site.group(1) if site else None
        if site_key is not None and site_key not in CATALOG:
            portfolio.invalid.append(f"{formatted} (site desconhecido: {site_key})")
            continue
        portfolio.entries.append(PortfolioEntry(cnj, sensitivity, tribunal_for(cnj), site_key))
    return portfolio
