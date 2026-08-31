from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID

from legal_monitor.domain.enums import ErrorCode
from legal_monitor.scheduler.policy import RetryPolicy


class RetryPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = RetryPolicy(base_seconds=60, maximum_seconds=600, jitter_ratio=0.2)
        self.job_id = UUID("00000000-0000-0000-0000-000000000001")
        self.now = datetime(2026, 8, 30, 20, 0, tzinfo=UTC)

    def test_backoff_is_deterministic_and_bounded(self) -> None:
        first = self.policy.next_retry_at(
            job_id=self.job_id,
            attempt=1,
            max_attempts=4,
            error_code=ErrorCode.TIMEOUT,
            now=self.now,
        )
        repeated = self.policy.next_retry_at(
            job_id=self.job_id,
            attempt=1,
            max_attempts=4,
            error_code=ErrorCode.TIMEOUT,
            now=self.now,
        )
        self.assertEqual(first, repeated)
        self.assertIsNotNone(first)
        delay = (first - self.now).total_seconds()  # type: ignore[operator]
        self.assertGreaterEqual(delay, 48)
        self.assertLessEqual(delay, 72)

    def test_blocking_error_is_never_retried(self) -> None:
        retry_at = self.policy.next_retry_at(
            job_id=self.job_id,
            attempt=1,
            max_attempts=4,
            error_code=ErrorCode.CAPTCHA_REQUIRED,
            now=self.now,
        )
        self.assertIsNone(retry_at)

    def test_last_attempt_is_not_retried(self) -> None:
        retry_at = self.policy.next_retry_at(
            job_id=self.job_id,
            attempt=4,
            max_attempts=4,
            error_code=ErrorCode.SOURCE_UNAVAILABLE,
            now=self.now,
        )
        self.assertIsNone(retry_at)

    def test_retry_after_is_honored_with_cap(self) -> None:
        retry_at = self.policy.next_retry_at(
            job_id=self.job_id,
            attempt=1,
            max_attempts=4,
            error_code=ErrorCode.RATE_LIMIT,
            now=self.now,
            retry_after_seconds=900,
        )
        self.assertEqual((retry_at - self.now).total_seconds(), 600)  # type: ignore[operator]


if __name__ == "__main__":
    unittest.main()
