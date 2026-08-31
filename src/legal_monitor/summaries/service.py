from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from legal_monitor.summaries.models import (
    ExtractedDocument,
    FactualSummaryDraft,
    PageEvidence,
    SummaryUnavailable,
    SummaryUnavailableReason,
)


class SummaryProvider(Protocol):
    prompt_version: str
    model_ref: str

    def create_draft(self, document: ExtractedDocument) -> FactualSummaryDraft: ...


@dataclass(frozen=True, slots=True)
class SummaryService:
    provider: SummaryProvider
    enabled: bool = False

    def summarize(self, document: ExtractedDocument) -> FactualSummaryDraft | SummaryUnavailable:
        if not self.enabled:
            return self._unavailable(SummaryUnavailableReason.DISABLED)
        try:
            draft = self.provider.create_draft(document)
        except Exception:
            return self._unavailable(SummaryUnavailableReason.PROVIDER_FAILURE)
        if draft.prompt_version != self.provider.prompt_version:
            return self._unavailable(SummaryUnavailableReason.INVALID_OUTPUT)
        if draft.model_ref != self.provider.model_ref:
            return self._unavailable(SummaryUnavailableReason.INVALID_OUTPUT)
        if not self._evidence_is_verifiable(draft, document):
            return self._unavailable(SummaryUnavailableReason.INVALID_OUTPUT)
        return draft

    def _unavailable(self, reason: SummaryUnavailableReason) -> SummaryUnavailable:
        return SummaryUnavailable(
            reason=reason,
            prompt_version=self.provider.prompt_version,
            model_ref=self.provider.model_ref,
        )

    @classmethod
    def _evidence_is_verifiable(
        cls,
        draft: FactualSummaryDraft,
        document: ExtractedDocument,
    ) -> bool:
        evidence = [item for fact in draft.iter_facts() for item in fact.evidence]
        evidence.extend(
            item for mentioned in draft.mentioned_dates_deadlines for item in mentioned.evidence
        )
        return bool(evidence) and all(cls._evidence_matches(item, document) for item in evidence)

    @staticmethod
    def _evidence_matches(evidence: PageEvidence, document: ExtractedDocument) -> bool:
        page_text = document.page_text(evidence.page)
        if page_text is None:
            return False
        normalized_page = " ".join(page_text.split()).casefold()
        normalized_excerpt = " ".join(evidence.excerpt.split()).casefold()
        return normalized_excerpt in normalized_page
