from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

DEADLINE_DISCLAIMER = "não validado como prazo processual"


def _required_text(value: str, *, label: str, maximum: int = 2_000) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{label} é obrigatório")
    if len(normalized) > maximum:
        raise ValueError(f"{label} excede {maximum} caracteres")
    return normalized


class SummaryReviewStatus(StrEnum):
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    UNAVAILABLE = "UNAVAILABLE"


class SummaryUnavailableReason(StrEnum):
    DISABLED = "DISABLED"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    INVALID_OUTPUT = "INVALID_OUTPUT"


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    number: int
    text: str

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("Número da página precisa ser positivo")
        if not self.text.strip():
            raise ValueError("Texto extraído da página não pode estar vazio")


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    pages: tuple[ExtractedPage, ...]
    demo_only: bool = False

    def __post_init__(self) -> None:
        if not self.pages:
            raise ValueError("Documento extraído precisa conter ao menos uma página")
        numbers = [page.number for page in self.pages]
        if numbers != sorted(set(numbers)):
            raise ValueError("Páginas extraídas precisam ser únicas e estar em ordem")

    def page_text(self, page_number: int) -> str | None:
        return next((page.text for page in self.pages if page.number == page_number), None)


@dataclass(frozen=True, slots=True)
class PageEvidence:
    page: int
    excerpt: str

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("Página da evidência precisa ser positiva")
        object.__setattr__(
            self,
            "excerpt",
            _required_text(self.excerpt, label="Trecho da evidência", maximum=500),
        )

    def as_dict(self) -> dict[str, Any]:
        return {"page": self.page, "excerpt": self.excerpt}


@dataclass(frozen=True, slots=True)
class CitedFact:
    text: str
    evidence: tuple[PageEvidence, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", _required_text(self.text, label="Fato"))
        if not self.evidence:
            raise ValueError("Todo fato do resumo precisa de evidência de página")

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "evidence": [item.as_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class MentionedDateOrDeadline:
    literal_text: str
    context: str
    evidence: tuple[PageEvidence, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "literal_text",
            _required_text(self.literal_text, label="Data ou prazo literal", maximum=300),
        )
        object.__setattr__(
            self,
            "context",
            _required_text(self.context, label="Contexto da data ou prazo", maximum=1_000),
        )
        if not self.evidence:
            raise ValueError("Data ou prazo mencionado precisa de evidência de página")

    def as_dict(self) -> dict[str, Any]:
        return {
            "literal_text": self.literal_text,
            "context": self.context,
            "classification": DEADLINE_DISCLAIMER,
            "evidence": [item.as_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class FactualSummaryDraft:
    document_type_normalized: str
    document_type_original: str
    decision_result: CitedFact | None
    central_reasons: tuple[CitedFact, ...]
    determinations: tuple[CitedFact, ...]
    mentioned_dates_deadlines: tuple[MentionedDateOrDeadline, ...]
    lawyer_summary: tuple[CitedFact, ...]
    uncertainties: tuple[str, ...]
    confidence: float
    prompt_version: str
    model_ref: str
    schema_version: str = "factual-summary-v1"
    review_status: SummaryReviewStatus = SummaryReviewStatus.REVIEW_REQUIRED

    def __post_init__(self) -> None:
        for field_name in (
            "document_type_normalized",
            "document_type_original",
            "prompt_version",
            "model_ref",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), label=field_name, maximum=200),
            )
        if not 0 <= self.confidence <= 1:
            raise ValueError("Confiança do resumo precisa ficar entre 0 e 1")
        if not 3 <= len(self.lawyer_summary) <= 8:
            raise ValueError("Resumo do advogado precisa conter de 3 a 8 pontos factuais")
        if self.review_status is not SummaryReviewStatus.REVIEW_REQUIRED:
            raise ValueError("Um resumo automático nasce obrigatoriamente para revisão humana")
        object.__setattr__(
            self,
            "uncertainties",
            tuple(
                _required_text(item, label="Incerteza", maximum=1_000)
                for item in self.uncertainties
            ),
        )

    @property
    def review_required(self) -> bool:
        return True

    def iter_facts(self) -> tuple[CitedFact, ...]:
        decision = (self.decision_result,) if self.decision_result else ()
        return decision + self.central_reasons + self.determinations + self.lawyer_summary

    def as_output_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "prompt_version": self.prompt_version,
            "model_ref": self.model_ref,
            "tipo_documento": {
                "normalizado": self.document_type_normalized,
                "original": self.document_type_original,
            },
            "decisao_resultado": (self.decision_result.as_dict() if self.decision_result else None),
            "fundamentos_centrais": [item.as_dict() for item in self.central_reasons],
            "determinacoes": [item.as_dict() for item in self.determinations],
            "datas_prazos_mencionados": [item.as_dict() for item in self.mentioned_dates_deadlines],
            "resumo_advogado": [item.as_dict() for item in self.lawyer_summary],
            "incertezas": list(self.uncertainties),
            "confidence": self.confidence,
            "review_status": self.review_status.value,
            "review_required": self.review_required,
            "prazo_calculado": False,
        }


@dataclass(frozen=True, slots=True)
class SummaryUnavailable:
    reason: SummaryUnavailableReason
    prompt_version: str
    model_ref: str
    schema_version: str = "factual-summary-v1"
    review_status: SummaryReviewStatus = SummaryReviewStatus.UNAVAILABLE

    def __post_init__(self) -> None:
        for field_name in ("prompt_version", "model_ref", "schema_version"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), label=field_name, maximum=200),
            )

    @property
    def review_required(self) -> bool:
        return True

    def as_output_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "prompt_version": self.prompt_version,
            "model_ref": self.model_ref,
            "reason": self.reason.value,
            "review_status": self.review_status.value,
            "review_required": self.review_required,
            "message": "Resumo indisponível - revisão humana necessária",
            "prazo_calculado": False,
        }
