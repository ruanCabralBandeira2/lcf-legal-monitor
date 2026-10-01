from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from legal_monitor.domain.cnj import CnjNumber
from legal_monitor.domain.enums import SourceSystem

JUSBR_SSO_HOST = "sso.cloud.pje.jus.br"
# Elementos que só existem no eproc com sessão ativa (a tela externa/de login não os tem).
EPROC_LOGGED_IN_SELECTOR = "#txtNumProcessoPesquisaRapida, a[href*='acao=sair']"


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
    # Elemento que só existe com sessão ativa (prova positiva de login). None = não verificado.
    logged_in_selector: str | None = None
    # Botão de login por certificado sem texto (ex.: imagem no IdServerJus do TJRJ).
    certificate_login_selector: str | None = None

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".jus.br"):
            raise ValueError("Fonte oficial exige HTTPS em domínio .jus.br")
        if self.system is SourceSystem.EPROC and self.logged_in_selector is None:
            # Todo eproc logado tem a busca rápida e o link de encerrar sessão.
            object.__setattr__(self, "logged_in_selector", EPROC_LOGGED_IN_SELECTOR)

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
            notes="eproc TJRJ 2º grau; login via SSO Jus.br (endereço conferido em 28/09/2026)",
            certificate_login_label="Certificado Digital",
        ),
        SourceEndpoint(
            key="tjrj-portal",
            tribunal="TJRJ",
            system=SourceSystem.LEGACY_DCP,
            base_url=(
                "https://www3.tjrj.jus.br/idserverjus-front/#/login"
                "?indGet=true&sgSist=PORTALSERVICOS"
            ),
            auth_realm="tjrj-portal",
            notes=(
                "TJRJ Portal de Serviços (processo eletrônico legado); login IdServerJus por "
                "certificado (imagem) ou usuário e senha"
            ),
            certificate_login_selector="img[src*='user-card']",
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
            key="eproc-jfrj-1g",
            tribunal="TRF2",
            system=SourceSystem.EPROC,
            base_url="https://eproc.jfrj.jus.br/eproc/",
            auth_realm="jfrj",
            notes=(
                "eproc Justiça Federal do RJ 1º grau (TRF2); login OAB + senha + 2FA ou "
                "certificado digital (botão conferido em 30/09/2026)"
            ),
            certificate_login_label="Certificado Digital",
            # O texto também aparece em links ocultos (um leva à Certisign): usar o botão.
            certificate_login_selector="input[onclick*='SubmitCert']",
        ),
        SourceEndpoint(
            key="eproc-trf2",
            tribunal="TRF2",
            system=SourceSystem.EPROC,
            base_url="https://eproc.trf2.jus.br/eproc/",
            auth_realm="trf2",
            notes=(
                "eproc TRF2 2º grau; login OAB (RJ000000) + senha + 2FA próprio ou "
                "certificado digital (botão conferido em 30/09/2026)"
            ),
            certificate_login_label="Certificado Digital",
            # O texto também aparece em links ocultos (um leva à Certisign): usar o botão.
            certificate_login_selector="input[onclick*='SubmitCert']",
        ),
        SourceEndpoint(
            key="eproc-trf4-2g",
            tribunal="TRF4",
            system=SourceSystem.EPROC,
            base_url="https://eproc.trf4.jus.br/eproc2trf4/",
            auth_realm="jusbr",
            notes="eproc TRF4 2º grau; SSO Jus.br; exige cadastro do advogado no TRF4",
            certificate_login_label="Certificado Digital",
        ),
        SourceEndpoint(
            key="pje-trt1-1g",
            tribunal="TRT1",
            system=SourceSystem.PJE,
            base_url="https://pje.trt1.jus.br/primeirograu/login.seam",
            auth_realm="trt1",
            headless_blocked=True,
            notes="PJe-JT TRT1 1º grau (PJe-KZ); login via SSO Jus.br; 403 a navegador headless",
            certificate_login_label="certificado",
        ),
        SourceEndpoint(
            key="pje-trt1-2g",
            tribunal="TRT1",
            system=SourceSystem.PJE,
            base_url="https://pje.trt1.jus.br/segundograu/login.seam",
            auth_realm="trt1",
            headless_blocked=True,
            notes="PJe-JT TRT1 2º grau (PJe-KZ); login via SSO Jus.br; 403 a navegador headless",
            certificate_login_label="certificado",
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

# Sequencial a partir de 0800000 é a faixa de numeração do PJe TJRJ.
PJE_TJRJ_SEQUENCE_START = 800_000
_FALLBACK: tuple[str, ...] = ("pdpj",)
# Tribunais que o robô sabe rotear (J, TR) -> sigla.
SUPPORTED_TRIBUNALS: dict[tuple[str, str], str] = {
    ("8", "19"): "TJRJ",
    ("4", "02"): "TRF2",
    ("4", "04"): "TRF4",
    ("5", "01"): "TRT1",
}


def candidate_keys(cnj: CnjNumber) -> tuple[str, ...]:
    """Ordem de preferência das fontes. É só preferência: a descoberta real registra onde
    o processo foi encontrado (`source_key`), e as rodadas seguintes vão direto nela."""
    justice, tribunal = cnj.digits[13], cnj.tribunal_code
    origin, sequence = cnj.digits[16:20], int(cnj.digits[0:7])
    second_instance = origin == "0000"
    if (justice, tribunal) == ("8", "19"):
        instances = ("2g", "1g") if second_instance else ("1g", "2g")
        if sequence >= PJE_TJRJ_SEQUENCE_START:
            keys = [f"{system}-tjrj-{i}" for i in instances for system in ("pje", "eproc")]
        else:
            # Numeração antiga: eproc (migrados) e, se não estiver lá, o processo eletrônico
            # do Portal de Serviços (informação do operador, 28/09/2026); PJe por último.
            keys = [f"eproc-tjrj-{instances[0]}", "tjrj-portal"]
            keys += [f"pje-tjrj-{instances[0]}"]
            keys += [f"{system}-tjrj-{instances[1]}" for system in ("eproc", "pje")]
        return (*keys, "pdpj")
    if (justice, tribunal) == ("4", "02"):
        pair = (
            ("eproc-trf2", "eproc-jfrj-1g") if second_instance else ("eproc-jfrj-1g", "eproc-trf2")
        )
        return (*pair, "pdpj")
    if (justice, tribunal) == ("4", "04"):
        return ("eproc-trf4-2g", "pdpj") if second_instance else _FALLBACK
    if (justice, tribunal) == ("5", "01"):
        pair = ("pje-trt1-2g", "pje-trt1-1g") if second_instance else ("pje-trt1-1g", "pje-trt1-2g")
        return (*pair, "pdpj")
    return _FALLBACK


def get_endpoint(key: str) -> SourceEndpoint:
    try:
        return CATALOG[key]
    except KeyError:
        raise UnknownSourceError(
            f"Fonte desconhecida: {key!r}. Opções: {', '.join(sorted(CATALOG))}"
        ) from None


def candidate_sources(cnj: CnjNumber) -> tuple[SourceEndpoint, ...]:
    """Roteamento local, sem rede: o número CNJ indica justiça e tribunal."""
    return tuple(CATALOG[key] for key in candidate_keys(cnj))


def tribunal_for(cnj: CnjNumber) -> str | None:
    return SUPPORTED_TRIBUNALS.get((cnj.digits[13], cnj.tribunal_code))
