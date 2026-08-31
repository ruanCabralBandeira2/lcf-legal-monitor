from __future__ import annotations

from dataclasses import dataclass

from legal_monitor.summaries.models import (
    CitedFact,
    ExtractedDocument,
    ExtractedPage,
    FactualSummaryDraft,
    PageEvidence,
)

FAKE_PAGE_TEXT = (
    "TRIBUNAL FICTÍCIO - DOCUMENTO EXCLUSIVO PARA DEMONSTRAÇÃO. "
    "DECISÃO. Considerando que a controvérsia pode ser esclarecida por prova documental, "
    "defiro a produção da prova documental. Intimem-se as partes para ciência. "
    "Nenhum prazo processual é calculado por esta fixture."
)

FAKE_EXTRACTED_DOCUMENT = ExtractedDocument(
    pages=(ExtractedPage(number=1, text=FAKE_PAGE_TEXT),),
    demo_only=True,
)


@dataclass(frozen=True, slots=True)
class FakeSummaryProvider:
    prompt_version: str = "factual-fixture-v1"
    model_ref: str = "fake-deterministic-v1"

    def create_draft(self, document: ExtractedDocument) -> FactualSummaryDraft:
        if document != FAKE_EXTRACTED_DOCUMENT or not document.demo_only:
            raise ValueError("Provedor fake aceita somente a fixture fixa de demonstração")
        reason_excerpt = "Considerando que a controvérsia pode ser esclarecida por prova documental"
        decision_excerpt = "defiro a produção da prova documental"
        notice_excerpt = "Intimem-se as partes para ciência"
        return FactualSummaryDraft(
            document_type_normalized="DECISAO",
            document_type_original="DECISÃO",
            decision_result=CitedFact(
                text="Foi deferida a produção de prova documental.",
                evidence=(PageEvidence(page=1, excerpt=decision_excerpt),),
            ),
            central_reasons=(
                CitedFact(
                    text="A prova documental foi considerada apta a esclarecer a controvérsia.",
                    evidence=(PageEvidence(page=1, excerpt=reason_excerpt),),
                ),
            ),
            determinations=(
                CitedFact(
                    text="As partes devem ser intimadas para ciência.",
                    evidence=(PageEvidence(page=1, excerpt=notice_excerpt),),
                ),
            ),
            mentioned_dates_deadlines=(),
            lawyer_summary=(
                CitedFact(
                    text="O documento fictício está identificado como decisão.",
                    evidence=(PageEvidence(page=1, excerpt="DECISÃO"),),
                ),
                CitedFact(
                    text="A produção de prova documental foi deferida.",
                    evidence=(PageEvidence(page=1, excerpt=decision_excerpt),),
                ),
                CitedFact(
                    text="Foi determinada a intimação das partes para ciência.",
                    evidence=(PageEvidence(page=1, excerpt=notice_excerpt),),
                ),
            ),
            uncertainties=(
                "Fixture demonstrativa; não representa processo, parte ou decisão real.",
            ),
            confidence=1.0,
            prompt_version=self.prompt_version,
            model_ref=self.model_ref,
        )
