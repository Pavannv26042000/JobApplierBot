"""Tests for the job deduplicator."""

import json
import os
import tempfile

import pytest

from core.job_deduplicator import JobDeduplicator


class TestDeduplication:
    """Test job dedup logic."""

    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.dedup = JobDeduplicator(store_path=self.tmp.name)

    def teardown_method(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_new_job_is_not_duplicate(self):
        assert not self.dedup.is_duplicate("Software Engineer", "Google")

    def test_applied_job_is_duplicate(self):
        self.dedup.mark_applied("Software Engineer", "Google", "linkedin")
        assert self.dedup.is_duplicate("Software Engineer", "Google")

    def test_skipped_job_is_duplicate(self):
        self.dedup.mark_skipped("Data Scientist", "Meta", "low_ats")
        assert self.dedup.is_duplicate("Data Scientist", "Meta")

    def test_cross_platform_dedup(self):
        self.dedup.mark_applied("Backend Developer", "Amazon", "naukri")
        # Same job on LinkedIn should be detected
        assert self.dedup.is_duplicate("Backend Developer", "Amazon")

    def test_case_insensitive(self):
        self.dedup.mark_applied("software engineer", "google", "linkedin")
        assert self.dedup.is_duplicate("Software Engineer", "Google")
        assert self.dedup.is_duplicate("SOFTWARE ENGINEER", "GOOGLE")

    def test_company_suffix_normalization(self):
        self.dedup.mark_applied("SWE", "Alten Global Technology Pvt Ltd", "naukri")
        assert self.dedup.is_duplicate("SWE", "Alten Global Technology")
        assert self.dedup.is_duplicate("SWE", "alten global technology pvt ltd")

    def test_get_previous_application(self):
        self.dedup.mark_applied("SWE", "Google", "linkedin", job_url="https://linkedin.com/jobs/123")
        prev = self.dedup.get_previous_application("SWE", "Google")
        assert prev is not None
        assert prev["platform"] == "linkedin"
        assert prev["job_url"] == "https://linkedin.com/jobs/123"

    def test_persistence(self):
        self.dedup.mark_applied("SWE", "Apple", "linkedin")
        # Load from same file
        dedup2 = JobDeduplicator(store_path=self.tmp.name)
        assert dedup2.is_duplicate("SWE", "Apple")

    def test_stats(self):
        self.dedup.mark_applied("SWE", "Google", "linkedin")
        self.dedup.mark_applied("SDE", "Amazon", "naukri")
        self.dedup.mark_skipped("PM", "Meta", "low_ats", "linkedin")
        stats = self.dedup.get_stats()
        assert stats["total_tracked"] == 3
        assert stats["applied"] == 2
        assert stats["skipped"] == 1
        assert stats["by_platform"]["linkedin"] == 2
        assert stats["by_platform"]["naukri"] == 1

    def test_clear(self):
        self.dedup.mark_applied("SWE", "Google", "linkedin")
        self.dedup.clear()
        assert not self.dedup.is_duplicate("SWE", "Google")
        assert self.dedup.get_stats()["total_tracked"] == 0

    def test_different_jobs_same_company(self):
        self.dedup.mark_applied("Frontend Developer", "Google", "linkedin")
        assert not self.dedup.is_duplicate("Backend Developer", "Google")

    def test_same_job_different_company(self):
        self.dedup.mark_applied("SWE", "Google", "linkedin")
        assert not self.dedup.is_duplicate("SWE", "Amazon")
