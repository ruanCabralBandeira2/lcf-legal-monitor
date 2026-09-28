from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.enums import SourceSystem

JUSBR_SSO_HOST = "sso.cloud.pje.jus.br"


class UnknownSourceError(ValueError):
    """Fonte não cadastrada no catálogo oficial."""


@dataclass(frozen=True, slots=True)
class SourceEndpoint:
    """Endereço oficial de uma fonte. Nunca contém credencial."""

    key: str
    tribunal: str
    system: SourceSystem
    base_url: str
    auth_realm: str
    notes: str
    # Texto do botão oficial de login por certificado (token USB). None = sem opção conhecida.
    certificate_login_label: str | None = None
    # A fonte recusa navegador sem janela (ex.: HTTP 403). Nunca contornar: usar janela visível.
    headless_blocked: bool = False

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".jus.br"):
            raise ValueError("Fonte oficial exige HTTPS em domínio .jus.br")

    @property
    def host(self) -> str:
        return urlparse(self.base_url).hostname or ""


# Endereços conferidos em 28/09/2026. eproc TJRJ e PDPJ autenticam pelo SSO Jus.br,
# por isso compartilham o mesmo realm: um login humano cobre as duas fontes.
CATALOG: dict[str, SourceEndpoint] = {
    endpoint.key: endpoint
    for endpoint in (
        SourceEndpoint(
            key="eproc-tjrj-1g",
            tribunal="TJRJ",
            system=SourceSystem.EPROC,
            base_url="https://eproc1g.tjrj.jus.br/eproc/",
            auth_realm="jusbr",
            notes="eproc TJRJ 1º grau; login via SSO Jus.br com 2FA",
            certificate_login_label="Certificado Digital",
        ),
        SourceEndpoint(
            key="eproc-tjrj-2g",
            tribunal="TJRJ",
            system=SourceSystem.EPROC,
            base_url="https://eproc2g.tjrj.jus.br/eproc/",
            auth_realm="jusbr",
            notes="eproc TJRJ 2º grau; endereço a confirmar no primeiro login",
            certificate_login_label="Certificado Digital",
        ),
        SourceEndpoint(
            key="pje-tjrj-1g",
            tribunal="TJRJ",
            system=SourceSystem.PJE,
            base_url="https://tjrj.pje.jus.br/1g/login.seam",
            auth_realm="jusbr",
            notes="PJe TJRJ 1º grau; login via SSO Jus.br; responde 403 a navegador headless",
            certificate_login_label="certificado digital",
            headless_blocked=True,
        ),
        SourceEndpoint(
            key="pje-tjrj-2g",
            tribunal="TJRJ",
            system=SourceSystem.PJE,
            base_url="https://tjrj.pje.jus.br/2g/login.seam",
            auth_realm="jusbr",
            notes="PJe TJRJ 2º grau; login via SSO Jus.br; comportamento headless a confirmar",
            certificate_login_label="certificado digital",
            headless_blocked=True,
        ),
        SourceEndpoint(
            key="eproc-trf2",
            tribunal="TRF2",
            system=SourceSystem.EPROC,
            base_url="https://eproc.trf2.jus.br/eproc/",
            auth_realm="trf2",
            notes="eproc TRF2; login OAB (RJ000000) + senha + 2FA próprio",
        ),
        SourceEndpoint(
            key="pdpj",
            tribunal="CNJ",
            system=SourceSystem.PDPJ,
            base_url="https://portaldeservicos.pdpj.jus.br/",
            auth_realm="jusbr",
            notes="Portal de Serviços PDPJ-Br/Jus.br; consulta complementar",
            certificate_login_label="certificado digital",
        ),
    )
}

# Segmento J.TR do número CNJ -> fontes candidatas, em ordem de preferência.
_ROUTES: dict[tuple[str, str], tuple[str, ...]] = {
    # Sequencial iniciado em "08" costuma nascer no PJe TJRJ; a ordem aqui é só preferência,
    # a descoberta real registra a fonte que encontrou o processo.
    ("8", "19"): ("eproc-tjrj-1g", "pje-tjrj-1g", "eproc-tjrj-2g", "pje-tjrj-2g", "pdpj"),
    ("4", "02"): ("eproc-trf2", "pdpj"),
}
_FALLBACK: tuple[str, ...] = ("pdpj",)


def get_endpoint(key: str) -> SourceEndpoint:
    try:
        return CATALOG[key]
    except KeyError:
        raise UnknownSourceError(
            f"Fonte desconhecida: {key!r}. Opções: {', '.join(sorted(CATALOG))}"
        ) from None


def candidate_sources(cnj: CnjNumber) -> tuple[SourceEndpoint, ...]:
    """Roteamento local, sem rede: o número CNJ indica justiça e tribunal."""
    justice = cnj.digits[13]
    keys = _ROUTES.get((justice, cnj.tribunal_code), _FALLBACK)
    return tuple(CATALOG[key] for key in keys)


def tribunal_for(cnj: CnjNumber) -> str:
    return candidate_sources(cnj)[0].tribunal
