"""
Unified configuration loader for JobApplierBot.
Loads from YAML config files with .env overrides for secrets.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env from project root (walks up to find it)
_project_root = Path(__file__).resolve().parent.parent
_env_path = _project_root / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()  # Try default locations


@dataclass
class GroqConfig:
    api_key: str = ""
    model: str = "llama-3.3-70b-versatile"
    temperature: float = 0.7
    max_tokens: int = 2048


@dataclass
class ATSConfig:
    target_score: int = 80
    min_to_apply: int = 60
    keywords_to_add: List[str] = field(default_factory=list)


@dataclass
class EmailConfig:
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    sender_email: str = ""
    sender_password: str = ""


@dataclass
class LinkedInConfig:
    username: str = ""
    password: str = ""
    phone_number: str = ""
    positions: List[str] = field(default_factory=list)
    locations: List[str] = field(default_factory=list)
    salary: str = "60,000"
    rate: str = "25"
    experience_level: List[int] = field(default_factory=list)
    blacklist: List[str] = field(default_factory=list)
    blacklist_titles: List[str] = field(default_factory=list)
    resume_path: str = ""
    cover_letter_path: str = ""
    output_filename: str = "output.csv"
    referral_enabled: bool = False
    referral_max_contacts: int = 3


@dataclass
class NaukriConfig:
    email: str = ""
    password: str = ""
    role: str = "Software Engineer"
    location: str = "bengaluru"
    max_pages: int = 10
    max_applications: int = 10
    custom_resume_path: str = "resume.pdf"


@dataclass
class NotificationConfig:
    enabled: bool = True
    email_enabled: bool = True
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


@dataclass
class AppConfig:
    """Top-level application configuration."""
    groq: GroqConfig = field(default_factory=GroqConfig)
    ats: ATSConfig = field(default_factory=ATSConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    linkedin: LinkedInConfig = field(default_factory=LinkedInConfig)
    naukri: NaukriConfig = field(default_factory=NaukriConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)

    # Paths
    resume_path: str = ""
    cover_letter_path: str = ""
    profile_path: str = ""


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """
    Load configuration from YAML file + environment variable overrides.

    Priority: ENV vars > YAML values > defaults.
    """
    data: Dict = {}

    # Try to load YAML config
    if config_path and Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        logger.info(f"Loaded config from {config_path}")
    else:
        logger.info("No YAML config found, using env vars + defaults")

    config = AppConfig()

    # --- Groq ---
    groq_data = data.get("groq", {}) or {}
    config.groq = GroqConfig(
        api_key=_env_or("GROQ_API_KEY", groq_data.get("api_key", "")),
        model=groq_data.get("model", "llama-3.3-70b-versatile"),
        temperature=float(groq_data.get("temperature", 0.7)),
        max_tokens=int(groq_data.get("max_tokens", 2048)),
    )

    # --- ATS ---
    ats_data = data.get("ats", {}) or {}
    config.ats = ATSConfig(
        target_score=int(ats_data.get("target_score", 80)),
        min_to_apply=int(ats_data.get("min_to_apply", 60)),
        keywords_to_add=ats_data.get("keywords_to_add", []) or [],
    )

    # --- Email ---
    email_data = data.get("email", {}) or {}
    config.email = EmailConfig(
        smtp_server=_env_or("SMTP_SERVER", email_data.get("smtp_server", "smtp.gmail.com")),
        smtp_port=int(_env_or("SMTP_PORT", str(email_data.get("smtp_port", 587)))),
        sender_email=_env_or("SENDER_EMAIL", email_data.get("sender_email", "")),
        sender_password=_env_or("SENDER_PASSWORD", email_data.get("sender_password", "")),
    )

    # --- LinkedIn ---
    li_data = data.get("linkedin", {}) or {}
    # Also support flat keys (old LinkedIn config format)
    config.linkedin = LinkedInConfig(
        username=_env_or("LINKEDIN_USERNAME", li_data.get("email", data.get("username", ""))),
        password=_env_or("LINKEDIN_PASSWORD", li_data.get("password", data.get("password", ""))),
        phone_number=_env_or("LINKEDIN_PHONE", li_data.get("phone_number", data.get("phone_number", ""))),
        positions=data.get("positions", li_data.get("positions", [])) or [],
        locations=data.get("locations", li_data.get("locations", [])) or [],
        salary=str(data.get("salary", li_data.get("salary", "60,000"))),
        rate=str(data.get("rate", li_data.get("rate", "25"))),
        experience_level=data.get("experience_level", li_data.get("experience_level", [])) or [],
        blacklist=data.get("blacklist", li_data.get("blacklist", [])) or [],
        blacklist_titles=data.get("blackListTitles", li_data.get("blacklist_titles", [])) or [],
        resume_path=os.getenv("RESUME_PATH", ""),
        cover_letter_path=os.getenv("COVER_LETTER_PATH", ""),
        output_filename=_first_valid(data.get("output_filename", []), "output.csv"),
        referral_enabled=data.get("referral", {}).get("enabled", False) if isinstance(data.get("referral"), dict) else False,
        referral_max_contacts=data.get("referral", {}).get("max_contacts", 3) if isinstance(data.get("referral"), dict) else 3,
    )

    # Upload paths (old format support)
    uploads = data.get("uploads", {}) or {}
    if uploads:
        if not config.linkedin.resume_path and uploads.get("Resume"):
            config.linkedin.resume_path = uploads["Resume"]
        if not config.linkedin.cover_letter_path and uploads.get("Cover Letter"):
            config.linkedin.cover_letter_path = uploads["Cover Letter"]

    # --- Naukri ---
    nk_data = data.get("naukri", {}) or {}
    config.naukri = NaukriConfig(
        email=_env_or("NAUKRI_EMAIL", nk_data.get("email", "")),
        password=_env_or("NAUKRI_PASSWORD", nk_data.get("password", "")),
        role=nk_data.get("role", "Software Engineer"),
        location=nk_data.get("location", "bengaluru"),
        max_pages=int(nk_data.get("max_pages", 10)),
        max_applications=int(nk_data.get("max_applications", 10)),
        custom_resume_path=nk_data.get("custom_resume_path", "resume.pdf"),
    )

    # --- Notifications ---
    notif_data = data.get("notifications", {}) or {}
    config.notifications = NotificationConfig(
        enabled=notif_data.get("enabled", True),
        email_enabled=notif_data.get("email_enabled", True),
        telegram_enabled=notif_data.get("telegram_enabled", False),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", notif_data.get("telegram_bot_token", "")),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", notif_data.get("telegram_chat_id", "")),
    )

    # --- Top-level paths ---
    config.resume_path = _env_or("RESUME_PATH", config.linkedin.resume_path or config.naukri.custom_resume_path)
    config.cover_letter_path = _env_or("COVER_LETTER_PATH", config.linkedin.cover_letter_path)

    return config


def _env_or(env_key: str, fallback: str) -> str:
    """Return env var if set and non-empty, otherwise fallback."""
    val = os.getenv(env_key, "")
    return val if val else fallback


def _first_valid(lst, default: str) -> str:
    """Return the first non-None item from a list, or the default."""
    if isinstance(lst, list):
        for item in lst:
            if item is not None:
                return str(item)
    elif lst is not None:
        return str(lst)
    return default
