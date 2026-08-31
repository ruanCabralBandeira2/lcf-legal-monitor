from __future__ import annotations

import unittest
from dataclasses import dataclass

from legal_monitor.summaries.fake import FAKE_EXTRACTED_DOCUMENT, FakeSummaryProvider
from legal_monitor.summaries.models import (
    DEADLINE_DISCLAIMER,
    CitedFact,
    ExtractedDocument,
    ExtractedPage,
    FactualSummaryDraft,
    MentionedDateOrDeadline,
    PageEvidence,
    SummaryUnavailable,
    SummaryUnavailableReason,
)
from legal_monitor.summaries.service import SummaryService


class SummaryContractTests(unittest.TestCase):
    def test_fake_summary_states_what_was_decided_with_page_evidence(self) -> None:
        result = SummaryService(FakeSummaryProvider(), enabled=True).summarize(
            FAKE_EXTRACTED_DOCUMENT
        )

        self.assertIsInstance(result, FactualSummaryDraft)
        assert isinstance(result, FactualSummaryDraft)
        self.assertEqual(
            result.decision_result.text, "Foi deferida a produção de prova documental."
        )
        self.assertEqual(result.decision_result.evidence[0].page, 1)
        self.assertTrue(result.review_required)
        self.assertFalse(result.as_output_json()["prazo_calculado"])

    def test_summary_is_unavailable_when_disabled_without_calling_provider(self) -> None:
        provider = FailingProvider()

        result = SummaryService(provider, enabled=False).summarize(FAKE_EXTRACTED_DOCUMENT)

        self.assertIsInstance(result, SummaryUnavailable)
        assert isinstance(result, SummaryUnavailable)
        self.assertEqual(result.reason, SummaryUnavailableReason.DISABLED)
        self.assertEqual(provider.calls, 0)

    def test_provider_failure_becomes_visible_fallback(self) -> None:
        provider = FailingProvider()

        result = SummaryService(provider, enabled=True).summarize(FAKE_EXTRACTED_DOCUMENT)

        self.assertIsInstance(result, SummaryUnavailable)
        assert isinstance(result, SummaryUnavailable)
        self.assertEqual(result.reason, SummaryUnavailableReason.PROVIDER_FAILURE)
        self.assertEqual(
            result.as_output_json()["message"],
            "Resumo indisponível - revisão humana necessária",
        )

    def test_invented_page_or_excerpt_is_rejected(self) -> None:
        for provider in (InvalidPageProvider(), InvalidExcerptProvider()):
            with self.subTest(provider=type(provider).__name__):
                result = SummaryService(provider, enabled=True).summarize(FAKE_EXTRACTED_DOCUMENT)
                self.assertIsInstance(result, SummaryUnavailable)
                assert isinstance(result, SummaryUnavailable)
                self.assertEqual(result.reason, SummaryUnavailableReason.INVALID_OUTPUT)

    def test_fact_without_page_evidence_is_invalid(self) -> None:
        with self.assertRaisesRegex(ValueError, "evidência"):
            CitedFact(text="Fato sem origem", evidence=())

    def test_mentioned_date_is_always_labeled_as_not_validated_deadline(self) -> None:
        value = MentionedDateOrDeadline(
            literal_text="10 dias",
            context="Trecho meramente fictício.",
            evidence=(PageEvidence(page=1, excerpt="prazo processual"),),
        )

        self.assertEqual(value.as_dict()["classification"], DEADLINE_DISCLAIMER)

    def test_summary_requires_three_to_eight_points(self) -> None:
        with self.assertRaisesRegex(ValueError, "3 a 8"):
            make_draft(PageEvidence(page=1, excerpt="DECISÃO"), lawyer_summary=())

    def test_fake_provider_rejects_non_demo_document(self) -> None:
        real_like_document = ExtractedDocument(
            pages=(ExtractedPage(number=1, text="Documento não autorizado."),),
            demo_only=False,
        )

        with self.assertRaisesRegex(ValueError, "somente a fixture"):
            FakeSummaryProvider().create_draft(real_like_document)


def make_draft(
    evidence: PageEvidence,
    *,
    lawyer_summary: tuple[CitedFact, ...] | None = None,
) -> FactualSummaryDraft:
    fact = CitedFact(text="Fato fictício.", evidence=(evidence,))
    return FactualSummaryDraft(
        document_type_normalized="DECISAO",
        document_type_original="DECISÃO",
        decision_result=fact,
        central_reasons=(fact,),
        determinations=(fact,),
        mentioned_dates_deadlines=(),
        lawyer_summary=lawyer_summary if lawyer_summary is not None else (fact, fact, fact),
        uncertainties=(),
        confidence=0.8,
        prompt_version="test-v1",
        model_ref="test-provider",
    )


@dataclass
class FailingProvider:
    prompt_version: str = "test-v1"
    model_ref: str = "test-provider"
    calls: int = 0

    def create_draft(self, document: ExtractedDocument) -> FactualSummaryDraft:
        self.calls += 1
        raise RuntimeError("detalhe sensível que não deve sair")


@dataclass
class InvalidPageProvider:
    prompt_version: str = "test-v1"
    model_ref: str = "test-provider"

    def create_draft(self, document: ExtractedDocument) -> FactualSummaryDraft:
        return make_draft(PageEvidence(page=99, excerpt="DECISÃO"))


@dataclass
class InvalidExcerptProvider:
    prompt_version: str = "test-v1"
    model_ref: str = "test-provider"

    def create_draft(self, document: ExtractedDocument) -> FactualSummaryDraft:
        return make_draft(PageEvidence(page=1, excerpt="resultado inventado"))


if __name__ == "__main__":
    unittest.main()
