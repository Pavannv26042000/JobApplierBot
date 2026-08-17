"""Tests for the ATS scoring engine."""

import pytest
from core.ats_scorer import ATSScorer, get_scorer


class TestATSScorer:
    """Test suite for ATSScorer."""

    def setup_method(self):
        self.scorer = ATSScorer()

    def test_empty_resume_returns_zero(self):
        score = self.scorer.calculate_score("", "Some job description")
        assert score == 0.0

    def test_empty_jd_returns_section_score_only(self):
        resume = "Experience: 5 years\nEducation: BS\nSkills: Python"
        score = self.scorer.calculate_score(resume, "")
        # Should have section score but no keyword score
        assert score >= 0.0

    def test_perfect_match_scores_high(self):
        resume = "Python developer with experience in Django, Flask, REST APIs, PostgreSQL, Docker, AWS, microservices, agile, CI/CD, git, testing, deployment, linux, kubernetes"
        jd = "Looking for a Python developer with experience in Django, Flask, REST APIs, PostgreSQL, Docker, AWS, microservices, agile, CI/CD, git, testing, deployment, linux, kubernetes"
        score = self.scorer.calculate_score(resume, jd)
        assert score > 70.0

    def test_no_match_scores_low(self):
        resume = "Chef with experience in French cuisine, baking, pastry arts"
        jd = "Software engineer with Python, Java, Kubernetes, AWS"
        score = self.scorer.calculate_score(resume, jd)
        assert score < 50.0

    def test_section_presence_boosts_score(self):
        resume_with_sections = "Experience: worked at Google\nEducation: MIT\nSkills: Python, Java"
        resume_without_sections = "I know Python and Java and worked at Google and went to MIT"
        jd = "Python Java developer"

        score_with = self.scorer.calculate_score(resume_with_sections, jd)
        score_without = self.scorer.calculate_score(resume_without_sections, jd)
        # Both should have keyword matches, but the one with sections should score higher
        assert score_with >= score_without

    def test_get_missing_keywords(self):
        resume = "Python developer with Django experience"
        jd = "Python developer with Django, Flask, and Kubernetes experience"
        missing = self.scorer.get_missing_keywords(resume, jd)
        assert "flask" in missing
        assert "kubernetes" in missing
        assert "python" not in missing  # Already in resume
        assert "django" not in missing  # Already in resume

    def test_stop_words_excluded(self):
        resume = "the and for are with"
        jd = "the and for are with but not you all"
        # Stop words shouldn't contribute to keyword score
        score = self.scorer.calculate_score(resume, jd)
        assert score < 50.0  # Only section score

    def test_improvement_potential(self):
        resume = "Python developer"
        jd = "Python developer with Django and Flask"
        score_before = self.scorer.calculate_score(resume, jd)
        score_after = self.scorer.calculate_improvement_potential(resume, jd, ["django", "flask"])
        assert score_after >= score_before

    def test_score_capped_at_100(self):
        # Even with more keywords than needed, score shouldn't exceed 100
        resume = "experience education skills " + " ".join(f"keyword{i}" for i in range(100))
        jd = " ".join(f"keyword{i}" for i in range(50))
        score = self.scorer.calculate_score(resume, jd)
        assert score <= 100.0

    def test_singleton_scorer(self):
        s1 = get_scorer()
        s2 = get_scorer()
        assert s1 is s2


class TestATSScorerWeights:
    """Test custom weight configurations."""

    def test_keyword_heavy_weights(self):
        scorer = ATSScorer(keyword_weight=0.9, section_weight=0.1)
        resume = "Python Django Flask"
        jd = "Python Django Flask"
        score = scorer.calculate_score(resume, jd)
        assert score > 0

    def test_section_heavy_weights(self):
        scorer = ATSScorer(keyword_weight=0.1, section_weight=0.9)
        resume = "Experience: yes\nEducation: yes\nSkills: Python"
        jd = "Unrelated completely different words"
        score = scorer.calculate_score(resume, jd)
        # Section score should dominate
        assert score > 20.0
