"""
Cross-platform job deduplication for JobApplierBot.
Prevents applying to the same job on both LinkedIn and Naukri.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)


class JobDeduplicator:
    """
    Tracks applied jobs across platforms to prevent duplicates.
    Uses normalized (title + company) hashing for cross-platform matching.
    """

    def __init__(self, store_path: str = "applied_jobs_index.json"):
        self.store_path = store_path
        self._index: Dict[str, Dict] = {}
        self._load()

    def _load(self) -> None:
        """Load the dedup index from disk."""
        if os.path.exists(self.store_path):
            try:
                with open(self.store_path, "r", encoding="utf-8") as f:
                    self._index = json.load(f)
                logger.info(f"Loaded {len(self._index)} jobs from dedup index")
            except Exception as e:
                logger.warning(f"Failed to load dedup index: {e}")
                self._index = {}

    def _save(self) -> None:
        """Persist the dedup index to disk."""
        Path(self.store_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump(self._index, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save dedup index: {e}")

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize text for consistent hashing."""
        text = text.lower().strip()
        # Remove common suffixes
        for suffix in [" pvt ltd", " private limited", " ltd", " inc", " llc",
                       " corp", " corporation", " co.", " technologies",
                       " technology", " solutions", " services", " global"]:
            text = text.replace(suffix, "")
        # Remove punctuation and extra whitespace
        text = re.sub(r'[^\w\s]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @staticmethod
    def _make_hash(title: str, company: str) -> str:
        """Create a consistent hash from job title + company."""
        normalized = f"{JobDeduplicator._normalize(title)}|{JobDeduplicator._normalize(company)}"
        return hashlib.md5(normalized.encode()).hexdigest()[:16]

    def is_duplicate(self, title: str, company: str) -> bool:
        """Check if a job has already been applied to (on any platform)."""
        job_hash = self._make_hash(title, company)
        return job_hash in self._index

    def get_previous_application(self, title: str, company: str) -> Optional[Dict]:
        """Get details of a previous application for this job."""
        job_hash = self._make_hash(title, company)
        return self._index.get(job_hash)

    def mark_applied(self, title: str, company: str, platform: str,
                     job_url: str = "", job_id: str = "",
                     ats_score: float = 0) -> None:
        """Record that a job has been applied to."""
        job_hash = self._make_hash(title, company)
        self._index[job_hash] = {
            "title": title,
            "company": company,
            "platform": platform,
            "job_url": job_url,
            "job_id": job_id,
            "ats_score": ats_score,
            "applied_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._save()
        logger.info(f"Marked as applied: '{title}' at '{company}' ({platform})")

    def mark_skipped(self, title: str, company: str, reason: str,
                     platform: str = "") -> None:
        """Record that a job was intentionally skipped."""
        job_hash = self._make_hash(title, company)
        self._index[job_hash] = {
            "title": title,
            "company": company,
            "platform": platform,
            "skipped": True,
            "skip_reason": reason,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._save()

    def get_stats(self) -> Dict:
        """Get deduplication statistics."""
        total = len(self._index)
        applied = sum(1 for v in self._index.values() if not v.get("skipped"))
        skipped = sum(1 for v in self._index.values() if v.get("skipped"))
        platforms: Dict[str, int] = {}
        for v in self._index.values():
            plat = v.get("platform", "unknown")
            platforms[plat] = platforms.get(plat, 0) + 1

        return {
            "total_tracked": total,
            "applied": applied,
            "skipped": skipped,
            "by_platform": platforms,
        }

    def get_all_applied_hashes(self) -> Set[str]:
        """Get all job hashes (useful for batch checking)."""
        return set(self._index.keys())

    def clear(self) -> None:
        """Clear the entire dedup index."""
        self._index = {}
        self._save()
        logger.info("Dedup index cleared")
