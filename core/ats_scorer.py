"""
ATS (Applicant Tracking System) scoring engine for JobApplierBot.
Shared between LinkedIn and Naukri bots.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional, Set

logger = logging.getLogger(__name__)


class ATSScorer:
    """Calculate ATS compatibility scores for resumes against job descriptions."""

    # Common stop words to exclude from keyword matching
    STOP_WORDS: Set[str] = {
        "the", "and", "for", "are", "but", "not", "you", "all", "can",
        "has", "her", "was", "one", "our", "out", "may", "also", "with",
        "this", "that", "have", "from", "they", "will", "been", "each",
        "make", "like", "more", "most", "only", "over", "such", "than",
        "them", "then", "very", "when", "come", "could", "into", "just",
        "must", "some", "take", "about", "after", "being", "below",
        "between", "both", "does", "doing", "during", "every", "here",
        "those", "under", "where", "which", "while", "would", "your",
        "should", "through", "working", "work", "experience", "required",
        "requirements", "ability", "including", "role", "team", "company",
        "looking", "join", "strong", "years", "using", "knowledge",
        "understanding", "please", "apply", "position", "candidate",
        "responsibilities", "qualifications", "preferred", "good", "well",
    }

    # Resume sections that ATS systems look for
    REQUIRED_SECTIONS = ["experience", "education", "skills"]
    BONUS_SECTIONS = ["projects", "certifications", "summary", "objective", "profile"]

    def __init__(self, keyword_weight: float = 0.7, section_weight: float = 0.3):
        self.keyword_weight = keyword_weight
        self.section_weight = section_weight

    def calculate_score(self, resume_text: str, job_description: str) -> float:
        """
        Calculate ATS score (0-100) based on keyword overlap + section presence.

        Args:
            resume_text: Full text content of the resume.
            job_description: Full text of the job description.

        Returns:
            Float score between 0 and 100.
        """
        if not resume_text:
            return 0.0

        resume_lc = resume_text.lower()
        jd_lc = (job_description or "").lower()

        keyword_score = self._keyword_overlap_score(resume_lc, jd_lc)
        section_score = self._section_completeness_score(resume_lc)

        final_score = (keyword_score * self.keyword_weight) + (section_score * self.section_weight)
        return min(round(final_score, 1), 100.0)

    def _keyword_overlap_score(self, resume_lc: str, jd_lc: str) -> float:
        """Score based on how many JD keywords appear in the resume."""
        jd_keywords = self._extract_meaningful_keywords(jd_lc)
        if not jd_keywords:
            return 0.0

        resume_keywords = self._extract_meaningful_keywords(resume_lc)
        common = jd_keywords.intersection(resume_keywords)

        return (len(common) / len(jd_keywords)) * 100

    def _section_completeness_score(self, resume_lc: str) -> float:
        """Score based on presence of required resume sections."""
        present = sum(1 for sec in self.REQUIRED_SECTIONS if sec in resume_lc)
        bonus = sum(0.5 for sec in self.BONUS_SECTIONS if sec in resume_lc)
        total = present + min(bonus, 1.0)  # Cap bonus contribution
        return min((total / len(self.REQUIRED_SECTIONS)) * 100, 100.0)

    def _extract_meaningful_keywords(self, text: str) -> Set[str]:
        """Extract words that are meaningful for ATS matching (excludes stop words)."""
        all_words = set(re.findall(r"\b[a-z]{3,}\b", text))
        return all_words - self.STOP_WORDS

    def get_missing_keywords(self, resume_text: str, job_description: str) -> List[str]:
        """Get JD keywords that are missing from the resume."""
        resume_lc = resume_text.lower()
        jd_lc = (job_description or "").lower()

        jd_keywords = self._extract_meaningful_keywords(jd_lc)
        resume_keywords = self._extract_meaningful_keywords(resume_lc)

        missing = jd_keywords - resume_keywords
        # Sort by length descending (longer = more specific = more valuable)
        return sorted(list(missing), key=len, reverse=True)

    def calculate_improvement_potential(self, resume_text: str,
                                        job_description: str,
                                        keywords_to_add: List[str]) -> float:
        """Preview what the score would be if we added certain keywords."""
        augmented = resume_text + "\n" + " ".join(keywords_to_add)
        return self.calculate_score(augmented, job_description)


# Module-level singleton for convenience
_default_scorer: Optional[ATSScorer] = None


def get_scorer() -> ATSScorer:
    """Get the default ATS scorer instance."""
    global _default_scorer
    if _default_scorer is None:
        _default_scorer = ATSScorer()
    return _default_scorer
