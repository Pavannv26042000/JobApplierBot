"""
Groq-powered AI service for JobApplierBot.
Replaces all Gemini and OpenAI integrations with Groq LPU inference.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional

from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)


class GroqAIService:
    """Unified AI service using Groq's LPU-accelerated inference."""

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile",
                 temperature: float = 0.7, max_tokens: int = 2048):
        if not api_key:
            logger.warning("No Groq API key provided. AI features will be disabled.")
            self.client = None
        else:
            self.client = Groq(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    def is_available(self) -> bool:
        return self.client is not None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _chat(self, messages: List[Dict], temperature: Optional[float] = None,
              max_tokens: Optional[int] = None) -> str:
        """Core chat completion with retry logic."""
        if not self.client:
            return ""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature or self.temperature,
            max_tokens=max_tokens or self.max_tokens,
        )
        return (response.choices[0].message.content or "").strip()

    @staticmethod
    def _parse_json_from_text(text: str) -> Dict:
        """Best-effort JSON extraction from LLM output."""
        if not text:
            return {"score": 50, "missing_keywords": [], "improvements": [], "suggestions": []}
        try:
            return json.loads(text)
        except Exception:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                return {"score": 50, "missing_keywords": [], "improvements": [], "suggestions": []}
            try:
                return json.loads(match.group(0))
            except Exception:
                return {"score": 50, "missing_keywords": [], "improvements": [], "suggestions": []}

    # ----- Public API Methods -----

    def analyze_jd(self, job_description: str, resume_text: str) -> Dict:
        """Analyze job description against resume, return match analysis."""
        if not self.is_available:
            return {"score": 50, "missing_keywords": [], "improvements": [], "suggestions": []}

        prompt = f"""Analyze this job description against the resume and provide:
1. Match score (0-100)
2. Missing keywords from JD not present in resume
3. Resume improvements needed
4. Specific suggestions to customize the resume

Job Description:
{job_description[:4000]}

Resume:
{resume_text[:4000]}

Return ONLY a JSON object with keys: score, missing_keywords, improvements, suggestions
No markdown, no explanation — just the raw JSON object."""

        try:
            response = self._chat(
                [{"role": "user", "content": prompt}],
                temperature=0.4,
            )
            return self._parse_json_from_text(response)
        except Exception as e:
            logger.error(f"JD analysis failed: {e}")
            return {"score": 50, "missing_keywords": [], "improvements": [], "suggestions": []}

    def generate_cover_letter(self, job_title: str, company: str,
                              resume_summary: str, skills: List[str],
                              job_description: str) -> str:
        """Generate a personalized cover letter."""
        if not self.is_available:
            return ""

        prompt = f"""Generate a professional cover letter for:
Job Title: {job_title}
Company: {company}

Applicant Summary: {resume_summary}
Key Skills: {', '.join(skills[:10])}

Job Description Excerpt:
{job_description[:1000]}

Requirements:
- 3-4 paragraphs
- Professional but personable tone
- Highlight relevant experience and skills
- Show genuine interest in the company
- No placeholder text — write the actual letter."""

        try:
            return self._chat(
                [{"role": "user", "content": prompt}],
                temperature=0.8,
                max_tokens=1500,
            )
        except Exception as e:
            logger.error(f"Cover letter generation failed: {e}")
            return ""

    def answer_application_question(self, question: str, resume_text: str,
                                     job_description: str = "") -> str:
        """Answer a job application form question using resume context."""
        if not self.is_available:
            return "user provided"

        prompt = f"""You are filling a job application form.
Answer this question concisely using the resume data below.

Question: {question}

Resume:
{resume_text[:3000]}

Job Description (may be empty):
{job_description[:2000]}

Rules:
- If yes/no question, output ONLY "Yes" or "No"
- If numeric question (e.g., "how many years"), output ONLY the number
- Keep answer under 200 characters
- Output ONLY the answer, no explanations or quotes"""

        try:
            answer = self._chat(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=200,
            )
            return answer.strip('"\'') if answer else "user provided"
        except Exception as e:
            logger.error(f"Question answering failed: {e}")
            return "user provided"

    def extract_hr_email(self, company_info: str) -> Dict:
        """Extract HR/recruiter email from company information text."""
        if not self.is_available:
            emails = re.findall(
                r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
                company_info,
            )
            return {"emails": emails, "suggested_emails": [], "confidence_score": 0.5}

        prompt = f"""Extract HR/recruiter email addresses from this text.
If no email found, suggest the most likely HR email format based on company domain.

Text: {company_info[:2000]}

Return ONLY a JSON object with keys: emails (array), suggested_emails (array), confidence_score (0-1)"""

        try:
            response = self._chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return self._parse_json_from_text(response)
        except Exception as e:
            logger.error(f"HR email extraction failed: {e}")
            emails = re.findall(
                r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
                company_info,
            )
            return {"emails": emails, "suggested_emails": [], "confidence_score": 0.3}

    def score_job_relevance(self, job_title: str, job_description: str,
                            resume_text: str) -> float:
        """AI-powered job relevance scoring (0-100). Use before applying."""
        if not self.is_available:
            return 50.0

        prompt = f"""Rate how well this candidate matches this job from 0-100.
Consider: skill match, experience level, domain fit, location.

Job Title: {job_title}
Job Description (excerpt): {job_description[:2000]}
Resume (excerpt): {resume_text[:2000]}

Output ONLY a single integer between 0 and 100. Nothing else."""

        try:
            response = self._chat(
                [{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=10,
            )
            # Extract number from response
            numbers = re.findall(r'\d+', response)
            if numbers:
                score = float(numbers[0])
                return min(max(score, 0), 100)
            return 50.0
        except Exception as e:
            logger.error(f"Relevance scoring failed: {e}")
            return 50.0

    def get_missing_keywords(self, job_description: str, resume_text: str) -> List[str]:
        """Get list of missing keywords from JD not present in resume."""
        analysis = self.analyze_jd(job_description, resume_text)
        missing = analysis.get("missing_keywords", [])
        if isinstance(missing, str):
            missing = re.split(r"[,\n]+", missing)
        return [str(k).strip() for k in (missing or []) if str(k).strip()]
