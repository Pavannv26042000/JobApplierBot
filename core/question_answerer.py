"""
Smart question answering system for job application forms.
Combines rule-based answers, cached Q&A, and AI fallback via Groq.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from core.ai_service import GroqAIService

logger = logging.getLogger(__name__)


class QuestionAnswerer:
    """Answers application form questions using rules, cache, and AI."""

    def __init__(self, ai_service: Optional[GroqAIService] = None,
                 qa_file: str = "qa.csv",
                 resume_text: str = "",
                 salary: str = "60,000"):
        self.ai_service = ai_service
        self.qa_file = Path(qa_file)
        self.resume_text = resume_text
        self.salary = salary
        self.answers: Dict[str, str] = {}
        self._load_qa_cache()

    def _load_qa_cache(self) -> None:
        """Load previously answered questions from CSV."""
        if self.qa_file.is_file():
            try:
                with open(self.qa_file, "r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        key = (row.get("Question") or "").lower().strip()
                        val = (row.get("Answer") or "").strip()
                        if key and val:
                            self.answers[key] = val
                logger.info(f"Loaded {len(self.answers)} cached Q&A pairs")
            except Exception as e:
                logger.warning(f"Failed to load QA cache: {e}")
        else:
            # Create empty CSV with headers
            with open(self.qa_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Question", "Answer"])

    def _save_answer(self, question: str, answer: str) -> None:
        """Save a new Q&A pair to the cache and CSV."""
        key = question.lower().strip()
        if key not in self.answers:
            self.answers[key] = answer
            with open(self.qa_file, "a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([question, answer])
            logger.info(f"Cached Q&A: '{question[:60]}...' → '{answer}'")

    def answer(self, question: str, job_description: str = "") -> str:
        """
        Answer a question using this priority:
        1. Cached answers (from qa.csv)
        2. Rule-based heuristics
        3. AI fallback (Groq)
        4. "user provided" (manual intervention needed)
        """
        q_lower = question.lower().strip()

        # 1. Check cache
        if q_lower in self.answers:
            return self.answers[q_lower]

        # 2. Rule-based
        rule_answer = self._rule_based_answer(q_lower)
        if rule_answer is not None:
            self._save_answer(question, rule_answer)
            logger.info(f"Rule-based answer: '{question[:60]}...' → '{rule_answer}'")
            return rule_answer

        # 3. AI fallback
        if self.ai_service and self.ai_service.is_available:
            ai_answer = self.ai_service.answer_application_question(
                question, self.resume_text, job_description
            )
            ai_answer = (ai_answer or "").strip()
            if ai_answer and ai_answer.lower() not in {"user provided", "unknown", "n/a", ""}:
                self._save_answer(question, ai_answer[:200])
                logger.info(f"AI answer: '{question[:60]}...' → '{ai_answer[:80]}'")
                return ai_answer[:200]

        # 4. Manual fallback
        logger.warning(f"Cannot auto-answer: '{question[:80]}'. Requires manual input.")
        self._save_answer(question, "user provided")
        return "user provided"

    def _rule_based_answer(self, q_lower: str) -> Optional[str]:
        """Try to answer using hardcoded rules. Returns None if no rule matches."""

        # Numeric questions
        if "how many" in q_lower and "year" in q_lower:
            if "experience" in q_lower:
                return "3"
            return "1"
        if "how many" in q_lower:
            return "1"

        # Yes/No questions
        if "sponsor" in q_lower:
            return "No"
        if "do you " in q_lower:
            return "Yes"
        if "have you " in q_lower:
            return "Yes"
        if "are you " in q_lower:
            if "comfortable" in q_lower or "willing" in q_lower or "legally" in q_lower:
                return "Yes"
            return "Yes"
        if "can you" in q_lower:
            return "Yes"
        if "us citizen" in q_lower:
            return "Yes"
        if "authorized" in q_lower and "work" in q_lower:
            return "Yes"

        # Salary
        if "salary" in q_lower or "compensation" in q_lower or "pay" in q_lower or "expectation" in q_lower:
            return self.salary

        # Notice Period / Availability
        if "notice" in q_lower or "availability" in q_lower or "how soon" in q_lower or "start date" in q_lower:
            return "Immediate / 15 days"

        # Relocation & Remote
        if "relocat" in q_lower or "hybrid" in q_lower or "remote" in q_lower or "work from home" in q_lower:
            return "Yes"

        # Education / Degree
        if "degree" in q_lower or "bachelor" in q_lower or "master" in q_lower or "qualification" in q_lower:
            return "Yes"

        # Demographics (prefer not to answer)
        if "gender" in q_lower:
            return "Male"
        for sensitive in ["race", "lgbtq", "ethnicity", "nationality", "disability",
                          "veteran", "sexual orientation"]:
            if sensitive in q_lower:
                return "Wish not to answer"
        if "government" in q_lower and "identify" in q_lower:
            return "I do not wish to self-identify"

        # Experience level
        if "experience" in q_lower and ("level" in q_lower or "years" in q_lower):
            return "3"

        # Notice period
        if "notice period" in q_lower:
            return "30 days"
        if "start date" in q_lower or "joining" in q_lower:
            return "Immediately"

        # No matching rule
        return None

    def find_similar_answer(self, question: str, threshold: float = 0.6) -> Optional[str]:
        """
        Find a semantically similar cached answer.
        Uses simple word overlap for now (can be upgraded to embeddings later).
        """
        q_words = set(question.lower().split())
        best_match = None
        best_score = 0.0

        for cached_q, cached_a in self.answers.items():
            cached_words = set(cached_q.split())
            if not cached_words:
                continue
            overlap = len(q_words & cached_words) / max(len(q_words), len(cached_words))
            if overlap > best_score and overlap >= threshold:
                best_score = overlap
                best_match = cached_a

        return best_match
