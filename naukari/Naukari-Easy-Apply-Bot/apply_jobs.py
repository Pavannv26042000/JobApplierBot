"""
Naukri Easy Apply Bot - Main Module
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.ai_service import GroqAIService
from core.ats_scorer import ATSScorer
from core.resume_manager import ResumeManager as CoreResumeManager, ResumeData
from core.config import load_config, AppConfig
from core.notifier import Notifier, EmailNotifier
from core.job_deduplicator import JobDeduplicator
from core.browser import create_browser
from selenium.webdriver.chrome.service import Service
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
import time
import random
import copy
import os
from pathlib import Path
import yaml
import json
import pandas as pd
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import re
import requests
from bs4 import BeautifulSoup
import spacy
from docx import Document
from PyPDF2 import PdfReader
from fpdf import FPDF
import subprocess
import tempfile
import logging
from typing import Dict, List, Optional, Tuple
import concurrent.futures
from queue import Queue
import threading
from dataclasses import dataclass
from enum import Enum
import hashlib
import pickle
from abc import ABC, abstractmethod

# AI Services

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('job_automation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load NLP model
try:
    nlp = spacy.load("en_core_web_sm")
except:
    logger.warning("spaCy model not found. Run: python -m spacy download en_core_web_sm")
    nlp = None

# ===== DATACLASSES =====
@dataclass
class Job:
    id: str
    title: str
    company: str
    location: str
    url: str
    description: str
    hr_email: Optional[str] = None
    jd_hash: Optional[str] = None
    applied: bool = False
    applied_date: Optional[str] = None
    ats_score: Optional[float] = None
    ats_score_before: Optional[float] = None
    ats_score_after: Optional[float] = None
    custom_resume_path: Optional[str] = None
    status: str = "pending"
    source: str = "naukri"

@dataclass
class Resume:
    name: str
    email: str
    phone: str
    summary: str
    experience: List[Dict]
    education: List[Dict]
    skills: List[str]
    projects: List[Dict]
    certifications: List[str]
    raw_text: str

class ApplicationStatus(Enum):
    PENDING = "pending"
    APPLIED = "applied"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    OFFER = "offer"

# ===== CONFIGURATION =====
class Config:
    def __init__(self, config_path="config.yaml"):
        with open(config_path, "r") as f:
            self.data = yaml.safe_load(f)
        
        # Naukri Config
        self.naukri_email = self.data["naukri"]["email"]
        self.naukri_password = self.data["naukri"]["password"]
        self.role = self.data["naukri"]["role"]
        self.location = self.data["naukri"]["location"]
        self.max_pages = self.data["naukri"]["max_pages"]
        self.max_applications = self.data["naukri"]["max_applications"]
        
        # Email Config
        self.smtp_server = self.data["email"]["smtp_server"]
        self.smtp_port = self.data["email"]["smtp_port"]
        self.sender_email = self.data["email"]["sender_email"]
        self.sender_password = self.data["email"]["sender_password"]
        
        # AI Config
        self.groq_api_key = os.getenv('GROQ_API_KEY', self.data.get('groq', {}).get('api_key', ''))
        
        # ATS Config
        self.ats_target_score = self.data.get("ats", {}).get("target_score", 80)
        self.min_ats_to_apply = self.data.get("ats", {}).get("min_to_apply", 60)

# ===== RESUME MANAGER =====
class ResumeManager:
    def __init__(self, config: Config):
        self.config = config
        self.resume = None
        self.last_customized_resume: Optional[Resume] = None
        self.load_resume()
    
    def load_resume(self, resume_path: Optional[str] = None):
        """Load resume from various formats"""
        if not resume_path:
            resume_path = os.getenv("RESUME_PATH") or self.config.data.get("naukri", {}).get("custom_resume_path") or self.config.data.get("resume_path") or "resume.pdf"
        
        if not os.path.exists(resume_path):
            logger.warning(f"Resume file '{resume_path}' not found on disk. Initializing empty profile. Set RESUME_PATH in .env to point to your PDF resume.")
            self.resume = Resume(
                name="Applicant",
                email=getattr(self.config, "naukri_email", ""),
                phone="",
                summary="",
                experience=[],
                education=[],
                skills=[],
                projects=[],
                certifications=[],
                raw_text=""
            )
            return

        if resume_path.endswith('.pdf'):
            self.resume = self._parse_pdf(resume_path)
        elif resume_path.endswith('.docx'):
            self.resume = self._parse_docx(resume_path)
        elif resume_path.endswith('.json'):
            self.resume = self._parse_json(resume_path)
        else:
            self.resume = self._parse_txt(resume_path)
        
        logger.info(f"Loaded resume for {self.resume.name if self.resume else 'applicant'}")
    
    def _parse_pdf(self, path: str) -> Resume:
        """Extract text from PDF resume"""
        if not os.path.exists(path):
            return self._parse_resume_text("")
        reader = PdfReader(path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        
        return self._parse_resume_text(text)
    
    def _parse_docx(self, path: str) -> Resume:
        """Extract text from DOCX resume"""
        if not os.path.exists(path):
            return self._parse_resume_text("")
        doc = Document(path)
        text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
        
        return self._parse_resume_text(text)
    
    def _parse_resume_text(self, text: str) -> Resume:
        """Parse resume text into structured format"""
        # Simple parsing logic - in production, use more sophisticated parsing
        lines = text.split('\n')
        
        # Extract name (usually first line)
        name = lines[0].strip() if lines else "Unknown"
        
        # Extract email
        email = ""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, text)
        if emails:
            email = emails[0]
        
        # Extract phone
        phone = ""
        phone_pattern = r'\b(?:\+?(\d{1,3}))?[-. (]*(\d{3})[-. )]*(\d{3})[-. ]*(\d{4})\b'
        phones = re.findall(phone_pattern, text)
        if phones:
            phone = ''.join(phones[0])
        
        # Parse sections (simplified)
        sections = self._extract_sections(text)
        
        return Resume(
            name=name,
            email=email,
            phone=phone,
            summary=sections.get("summary", ""),
            experience=sections.get("experience", []),
            education=sections.get("education", []),
            skills=sections.get("skills", []),
            projects=sections.get("projects", []),
            certifications=sections.get("certifications", []),
            raw_text=text
        )
    
    def _extract_sections(self, text: str) -> Dict:
        """Extract resume sections using keyword matching"""
        sections = {
            "summary": "",
            "experience": [],
            "education": [],
            "skills": [],
            "projects": [],
            "certifications": []
        }
        
        # Simple section extraction (enhance with NLP in production)
        lines = text.split('\n')
        current_section = None
        
        for line in lines:
            line_lower = line.lower().strip()
            
            if any(keyword in line_lower for keyword in ["summary", "objective", "profile"]):
                current_section = "summary"
            elif any(keyword in line_lower for keyword in ["experience", "work history"]):
                current_section = "experience"
            elif any(keyword in line_lower for keyword in ["education", "academic"]):
                current_section = "education"
            elif any(keyword in line_lower for keyword in ["skills", "technical skills"]):
                current_section = "skills"
            elif any(keyword in line_lower for keyword in ["projects", "portfolio"]):
                current_section = "projects"
            elif any(keyword in line_lower for keyword in ["certifications", "certificate"]):
                current_section = "certifications"
            elif current_section and line.strip():
                if current_section == "summary":
                    sections["summary"] += line + " "
                elif current_section == "skills":
                    # Extract skills from line
                    skills = re.split(r'[,|;]', line)
                    sections["skills"].extend([s.strip() for s in skills if s.strip()])
        
        return sections
    
    def calculate_ats_score(self, job_description: str, resume: Optional[Resume] = None) -> float:
        """Calculate ATS compatibility score for a given resume."""
        resume_obj = resume or self.resume
        if not resume_obj:
            return 0.0

        resume_text = resume_obj.raw_text.lower()
        jd_text = job_description.lower()
        
        # Keyword matching
        jd_keywords = set(re.findall(r'\b[a-z]{3,}\b', jd_text))
        resume_keywords = set(re.findall(r'\b[a-z]{3,}\b', resume_text))
        
        common_keywords = jd_keywords.intersection(resume_keywords)
        
        # Calculate score
        if len(jd_keywords) > 0:
            keyword_score = len(common_keywords) / len(jd_keywords) * 100
        else:
            keyword_score = 0
        
        # Section completeness scoring
        section_score = 0
        required_sections = ["experience", "education", "skills"]
        present_sections = sum(1 for section in required_sections if getattr(resume_obj, section))
        section_score = (present_sections / len(required_sections)) * 100
        
        # Final weighted score
        final_score = (keyword_score * 0.7) + (section_score * 0.3)
        
        return min(final_score, 100)

    def _build_resume_raw_text(self, resume: Resume) -> str:
        """Create a flat text representation used for ATS scoring and AI context."""
        parts: List[str] = []
        parts.append(resume.name or "")
        parts.append(resume.email or "")
        parts.append(resume.phone or "")
        parts.append(f"Summary: {resume.summary or ''}".strip())

        if resume.skills:
            parts.append(f"Skills: {', '.join(resume.skills)}")

        for exp in resume.experience or []:
            parts.append(
                " ".join(
                    [
                        exp.get("title", ""),
                        exp.get("company", ""),
                        exp.get("location", ""),
                        exp.get("description", ""),
                    ]
                )
            )

        for edu in resume.education or []:
            parts.append(
                " ".join(
                    [
                        edu.get("degree", ""),
                        edu.get("institution", ""),
                        edu.get("cgpa", ""),
                        edu.get("startDate", ""),
                        edu.get("endDate", ""),
                    ]
                )
            )

        for proj in resume.projects or []:
            parts.append(
                " ".join(
                    [
                        proj.get("name", ""),
                        proj.get("description", ""),
                    ]
                )
            )

        for cert in resume.certifications or []:
            parts.append(str(cert))

        return "\n".join([p for p in parts if p]).strip()
    
    def customize_for_jd(self, job_description: str, output_path: str) -> str:
        """Customize resume for specific job description"""
        if not self.resume:
            return ""

        # Analyze JD and get missing keywords
        ai_service = GroqAIService(api_key=self.config.groq_api_key)
        analysis = ai_service.analyze_jd(job_description, self.resume.raw_text)

        tailored_resume = copy.deepcopy(self.resume)

        missing_keywords = analysis.get("missing_keywords", [])
        if isinstance(missing_keywords, str):
            missing_keywords = re.split(r"[,\n]+", missing_keywords)
        missing_keywords = [str(k).strip() for k in (missing_keywords or []) if str(k).strip()]

        existing_skills_lc = {s.strip().lower() for s in (tailored_resume.skills or []) if s}
        for kw in missing_keywords[:15]:
            kw_lc = kw.lower()
            if kw_lc not in existing_skills_lc:
                tailored_resume.skills.append(kw)
                existing_skills_lc.add(kw_lc)

        # Update summary with the first suggestion/improvement snippet (if available).
        suggestions = analysis.get("suggestions") or []
        improvements = analysis.get("improvements") or []
        summary_snippet = None
        for candidate in (suggestions if isinstance(suggestions, list) else [suggestions]) + (
            improvements if isinstance(improvements, list) else [improvements]
        ):
            if isinstance(candidate, str) and candidate.strip():
                summary_snippet = candidate.strip()
                break
        if summary_snippet:
            base = (tailored_resume.summary or "").strip()
            tailored_resume.summary = (base + " " if base else "") + summary_snippet[:300]

        tailored_resume.raw_text = self._build_resume_raw_text(tailored_resume)
        self.last_customized_resume = tailored_resume

        # `output_path` is expected to be a PDF path; we compile from a .tex sibling.
        output_pdf_path = output_path if output_path.lower().endswith(".pdf") else output_path + ".pdf"
        output_tex_path = str(Path(output_pdf_path).with_suffix(".tex"))

        pdf_path = self.generate_latex_resume(output_path=output_tex_path, resume=tailored_resume)
        logger.info(f"Customized resume saved to {pdf_path}")
        return pdf_path
    
    def generate_latex_resume(self, output_path: str = "resume.tex", resume: Optional[Resume] = None) -> str:
        """Generate resume PDF from structured data (LaTeX preferred; fallback PDF if LaTeX isn't installed)."""
        resume_obj = resume or self.resume
        if not resume_obj:
            raise ValueError("No resume loaded to generate output.")

        latex_template = r"""
\documentclass[11pt,a4paper]{moderncv}
\moderncvstyle{classic}
\moderncvcolor{blue}
\usepackage[scale=0.75]{geometry}

\name{%s}{}
\address{}{}{}
\phone[mobile]{%s}
\email{%s}

\begin{document}
\makecvtitle

\section{Summary}
%s

\section{Experience}
%s

\section{Education}
%s

\section{Skills}
%s

\section{Projects}
%s

\section{Certifications}
%s

\end{document}
        """ % (
            self._latex_escape(resume_obj.name),
            self._latex_escape(resume_obj.phone),
            self._latex_escape(resume_obj.email),
            self._latex_escape(resume_obj.summary or ""),
            self._format_latex_experience(resume_obj),
            self._format_latex_education(resume_obj),
            self._format_latex_skills(resume_obj),
            self._format_latex_projects(resume_obj),
            self._format_latex_certifications(resume_obj),
        )

        output_pdf_path = str(Path(output_path).with_suffix(".pdf"))
        Path(output_pdf_path).parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(latex_template)

        compiled_ok = self._compile_latex(output_path)
        if compiled_ok and os.path.exists(output_pdf_path):
            return output_pdf_path

        # Fallback: generate a simple PDF from raw resume text.
        self._generate_pdf_fallback(self._build_resume_raw_text(resume_obj), output_pdf_path)
        return output_pdf_path
    
    def _format_latex_experience(self, resume: Resume) -> str:
        """Format experience for LaTeX."""
        formatted = ""
        for exp in resume.experience or []:
            formatted += r"\cventry{%s}{%s}{%s}{%s}{}{%s}\n" % (
                self._latex_escape(exp.get('dates', '') or ''),
                self._latex_escape(exp.get('title', '') or ''),
                self._latex_escape(exp.get('company', '') or ''),
                self._latex_escape(exp.get('location', '') or ''),
                self._latex_escape(exp.get('description', '') or ''),
            )
        return formatted
    
    def _format_latex_skills(self, resume: Resume) -> str:
        """Format skills for LaTeX."""
        return ", ".join([self._latex_escape(s) for s in (resume.skills or []) if s])

    def _latex_escape(self, text: str) -> str:
        """Escape minimal LaTeX special characters to reduce compile failures."""
        if text is None:
            return ""
        s = str(text)
        return (
            s.replace("\\", r"\textbackslash{}")
            .replace("&", r"\&")
            .replace("%", r"\%")
            .replace("#", r"\#")
            .replace("_", r"\_")
            .replace("{", r"\{")
            .replace("}", r"\}")
            .replace("~", r"\textasciitilde{}")
            .replace("^", r"\^{}")
        )

    def _format_latex_education(self, resume: Resume) -> str:
        formatted = ""
        for edu in resume.education or []:
            years = edu.get("endDate") or edu.get("startDate") or ""
            formatted += r"\cventry{%s}{%s}{%s}{%s}{%s}{}\n" % (
                self._latex_escape(years),
                self._latex_escape(edu.get("degree", "") or ""),
                self._latex_escape(edu.get("institution", "") or ""),
                self._latex_escape(edu.get("location", "") or ""),
                self._latex_escape(edu.get("cgpa", "") or ""),
            )
        return formatted

    def _format_latex_projects(self, resume: Resume) -> str:
        formatted = ""
        for proj in resume.projects or []:
            year = proj.get("year", "") if isinstance(proj, dict) else ""
            name = proj.get("name", "") if isinstance(proj, dict) else str(proj)
            desc = proj.get("description", "") if isinstance(proj, dict) else ""
            formatted += r"\cventry{%s}{%s}{%s}{%s}{}{%s}\n" % (
                self._latex_escape(year),
                self._latex_escape(name),
                self._latex_escape(""),
                self._latex_escape(""),
                self._latex_escape(desc),
            )
        return formatted

    def _format_latex_certifications(self, resume: Resume) -> str:
        formatted = ""
        for cert in resume.certifications or []:
            cert_name = cert if isinstance(cert, str) else cert.get("name", "")
            formatted += r"\cventry{%s}{%s}{%s}{%s}{}{}\n" % (
                self._latex_escape(""),
                self._latex_escape(cert_name),
                self._latex_escape(""),
                self._latex_escape(""),
            )
        return formatted

    def _generate_pdf_fallback(self, resume_text: str, output_pdf_path: str) -> None:
        """Generate a plain text PDF when LaTeX compilation isn't available."""
        output_dir = Path(output_pdf_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Helvetica", size=10)

        epw = pdf.epw
        for line in (resume_text or "").splitlines():
            pdf.x = pdf.l_margin
            pdf.multi_cell(epw, 5, line.strip() if line.strip() else " ", new_x="LMARGIN", new_y="NEXT")

        pdf.output(output_pdf_path)

    def _compile_latex(self, tex_path: str) -> bool:
        """Compile LaTeX to PDF. Returns True if the PDF exists after compilation."""
        expected_pdf_path = str(Path(tex_path).with_suffix(".pdf"))
        tex_dir = str(Path(tex_path).parent)
        tex_filename = Path(tex_path).name

        try:
            subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", tex_filename],
                cwd=tex_dir,
                check=True,
                capture_output=True,
            )
            logger.info("Compiled LaTeX resume to PDF")
            return os.path.exists(expected_pdf_path)
        except subprocess.CalledProcessError as e:
            logger.error(f"LaTeX compilation failed: {e.stderr}")
            return False
        except FileNotFoundError:
            logger.warning("pdflatex not found. Install texlive to compile LaTeX.")
            return False

# ===== EMAIL MANAGER =====
class EmailManager:
    def __init__(self, config: Config):
        self.config = config
        self.smtp_server = config.smtp_server
        self.smtp_port = config.smtp_port
        self.sender_email = config.sender_email
        self.sender_password = config.sender_password
    
    def send_hr_email(self, job: Job, resume: Resume, 
                     cover_letter: Optional[str] = None) -> bool:
        """Send email to HR with resume and cover letter"""
        if not job.hr_email:
            logger.warning(f"No HR email for {job.company}")
            return False
        
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = job.hr_email
            msg['Subject'] = f"Application for {job.title} - {resume.name}"
            
            # Email body
            body = f"""
Dear Hiring Manager,

I am writing to express my interest in the {job.title} position at {job.company}. 
My experience and skills align well with your requirements.

{cover_letter if cover_letter else ''}

Please find my resume attached for your review.

Best regards,
{resume.name}
{resume.phone}
{resume.email}
LinkedIn: [Your LinkedIn Profile]
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            # Attach resume
            resume_path = job.custom_resume_path or "resume.pdf"
            if os.path.exists(resume_path):
                with open(resume_path, "rb") as f:
                    attach = MIMEApplication(f.read(), _subtype="pdf")
                    attach.add_header('Content-Disposition', 'attachment', 
                                    filename=os.path.basename(resume_path))
                    msg.attach(attach)
            
            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)
            
            logger.info(f"Email sent to HR at {job.company}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False
    
    def send_followup_email(self, job: Job, resume: Resume, 
                          days_after: int = 7) -> bool:
        """Send follow-up email after initial application"""
        followup_subject = f"Follow-up: Application for {job.title}"
        followup_body = f"""
Dear Hiring Manager,

I wanted to follow up on my application for the {job.title} position 
at {job.company}, which I submitted on {job.applied_date}.

I remain very interested in this opportunity and believe my skills 
in {', '.join(resume.skills[:3])} would be a great fit for your team.

Thank you for your time and consideration.

Best regards,
{resume.name}
        """
        
        return self._send_simple_email(job.hr_email, followup_subject, followup_body)
    
    def _send_simple_email(self, to_email: str, subject: str, body: str) -> bool:
        """Send a simple email without attachments"""
        try:
            msg = MIMEText(body)
            msg['Subject'] = subject
            msg['From'] = self.sender_email
            msg['To'] = to_email
            
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)
            
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

# ===== JOB SCRAPER =====
class JobScraper:
    def __init__(self, config: Config, driver: webdriver.Chrome):
        self.config = config
        self.driver = driver
        self.wait = WebDriverWait(driver, 15)
        self.job_queue = Queue()
        self.processed_jobs = {}

    def _login_naukri(self) -> bool:
        """Log in to Naukri using credentials from env/config."""
        email = getattr(self.config, "naukri_email", "") or os.getenv("NAUKRI_EMAIL", "")
        password = getattr(self.config, "naukri_password", "") or os.getenv("NAUKRI_PASSWORD", "")

        if not email or not password:
            logger.warning("Naukri email/password not set in .env or Config.yaml. Continuing without logging in.")
            return False

        logger.info(f"Logging in to Naukri as {email}...")
        try:
            self.driver.get("https://www.naukri.com/nnetwork/login")
            time.sleep(3)

            # Check if already logged in
            if "nnetwork" not in self.driver.current_url.lower() and "login" not in self.driver.current_url.lower():
                logger.info("Already logged in to Naukri.")
                return True

            # Find username field
            user_input = None
            for selector in ["#usernameField", "input[placeholder*='Email']", "input[placeholder*='Username']", "input[type='text']"]:
                try:
                    user_input = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if user_input.is_displayed():
                        break
                except Exception:
                    continue

            if user_input:
                user_input.clear()
                user_input.send_keys(email)
                time.sleep(1)

            # Find password field
            pw_input = None
            for selector in ["#passwordField", "input[type='password']"]:
                try:
                    pw_input = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if pw_input.is_displayed():
                        break
                except Exception:
                    continue

            if pw_input:
                pw_input.clear()
                pw_input.send_keys(password)
                time.sleep(1)

            # Find submit button
            submit_btn = None
            for selector in ["//button[@type='submit']", "//button[contains(text(), 'Login')]", "button.waves-effect"]:
                try:
                    if "//" in selector:
                        submit_btn = self.driver.find_element(By.XPATH, selector)
                    else:
                        submit_btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if submit_btn and submit_btn.is_displayed():
                        break
                except Exception:
                    continue

            if submit_btn:
                self.driver.execute_script("arguments[0].click();", submit_btn)
                time.sleep(5)

            logger.info("Naukri login submitted.")
            return True

        except Exception as e:
            logger.error(f"Naukri login failed: {e}")
            return False

    def scrape_naukri(self) -> List[Job]:
        """Scrape jobs from Naukri"""
        jobs = []
        base_url = "https://www.naukri.com"
        
        for page in range(1, self.config.max_pages + 1):
            search_url = f"{base_url}/{self.config.role.replace(' ', '-')}-jobs"
            if self.config.location:
                search_url += f"-in-{self.config.location.replace(' ', '-')}"
            if page > 1:
                search_url += f"-{page}"
            
            logger.info(f"Scraping page {page}: {search_url}")
            self.driver.get(search_url)
            time.sleep(3)
            
            # Handle CAPTCHA
            if "verify" in self.driver.current_url:
                input("CAPTCHA detected. Solve manually and press Enter...")
            
            try:
                # Support multiple Naukri DOM variants
                job_cards = self.driver.find_elements(
                    By.XPATH, "//div[contains(@class, 'srp-jobtuple-wrapper')] | //div[contains(@class, 'cust-job-tuple')] | //article[contains(@class, 'jobTuple')] | //div[contains(@class, 'jobTuple')]"
                )
                if not job_cards:
                    # Fallback wait
                    try:
                        self.wait.until(
                            EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'srp-jobtuple-wrapper')] | //article"))
                        )
                        job_cards = self.driver.find_elements(
                            By.XPATH, "//div[contains(@class, 'srp-jobtuple-wrapper')] | //div[contains(@class, 'cust-job-tuple')] | //article[contains(@class, 'jobTuple')] | //div[contains(@class, 'jobTuple')]"
                        )
                    except Exception:
                        pass
                
                for card in job_cards[:10]:  # Limit per page
                    try:
                        title_elem = card.find_element(By.CSS_SELECTOR, "a.title, a.title-line, .title a")
                        title = title_elem.text.strip()
                        try:
                            company = card.find_element(By.CSS_SELECTOR, "a.subTitle, a.comp-name, span.comp-name, .comp-name").text.strip()
                        except Exception:
                            company = "Unknown Company"
                        try:
                            location = card.find_element(By.CSS_SELECTOR, ".loc, span.loc-wrap, .location, span.locWraper").text.strip()
                        except Exception:
                            location = self.config.location or "India"
                        link = title_elem.get_attribute("href")
                        
                        job_id = hashlib.md5(link.encode()).hexdigest()[:10]
                        
                        job = Job(
                            id=job_id,
                            title=title,
                            company=company,
                            location=location,
                            url=link,
                            description="",
                            source="naukri"
                        )
                        
                        jobs.append(job)
                        
                    except Exception as e:
                        logger.debug(f"Skipping card: {e}")
                        continue
                
            except Exception as e:
                logger.error(f"Error scraping page {page}: {e}")
        
        logger.info(f"Scraped {len(jobs)} jobs from Naukri")
        return jobs
    
    def scrape_linkedin(self) -> List[Job]:
        """Scrape jobs from LinkedIn (requires login)"""
        jobs = []
        
        # LinkedIn scraping logic (simplified)
        # Note: LinkedIn has strict anti-scraping measures
        try:
            self.driver.get("https://www.linkedin.com/jobs")
            time.sleep(5)
            
            # Login if needed
            if "login" in self.driver.current_url:
                self._login_linkedin()
            
            # Search jobs
            search_box = self.wait.until(
                EC.presence_of_element_located((By.XPATH, "//input[contains(@placeholder, 'Search jobs')]"))
            )
            search_box.send_keys(self.config.role)
            
            if self.config.location:
                location_box = self.driver.find_element(
                    By.XPATH, "//input[contains(@placeholder, 'Search location')]"
                )
                location_box.send_keys(self.config.location)
            
            search_button = self.driver.find_element(
                By.XPATH, "//button[contains(@aria-label, 'Search')]"
            )
            search_button.click()
            time.sleep(5)
            
            # Extract jobs (simplified - LinkedIn DOM is complex)
            job_listings = self.driver.find_elements(
                By.CSS_SELECTOR, "div.job-card-container"
            )
            
            for listing in job_listings[:10]:
                try:
                    title = listing.find_element(By.CSS_SELECTOR, "h3").text
                    company = listing.find_element(By.CSS_SELECTOR, "h4").text
                    link = listing.find_element(By.CSS_SELECTOR, "a").get_attribute("href")
                    
                    job = Job(
                        id=hashlib.md5(link.encode()).hexdigest()[:10],
                        title=title,
                        company=company,
                        location=self.config.location,
                        url=link,
                        description="",
                        source="linkedin"
                    )
                    jobs.append(job)
                    
                except Exception as e:
                    logger.debug(f"Skipping LinkedIn job: {e}")
        
        except Exception as e:
            logger.error(f"LinkedIn scraping failed: {e}")
        
        return jobs
    
    def _login_linkedin(self):
        """Login to LinkedIn"""
        email_input = self.wait.until(
            EC.presence_of_element_located((By.ID, "username"))
        )
        email_input.send_keys(self.config.data["linkedin"]["email"])
        
        password_input = self.driver.find_element(By.ID, "password")
        password_input.send_keys(self.config.data["linkedin"]["password"])
        
        login_button = self.driver.find_element(
            By.XPATH, "//button[@type='submit']"
        )
        login_button.click()
        time.sleep(5)
    
    def extract_job_details(self, job: Job) -> Job:
        """Extract detailed job description and HR info"""
        try:
            self.driver.get(job.url)
            time.sleep(3)
            
            # Extract job description
            try:
                jd_element = self.driver.find_element(
                    By.CSS_SELECTOR, ".jd-desc, .description__text"
                )
                job.description = jd_element.text[:5000]  # Limit length
            except:
                job.description = "Description not available"
            
            # Generate hash for JD
            job.jd_hash = hashlib.md5(job.description.encode()).hexdigest()[:10]
            
            # Try to extract HR/company email
            try:
                company_info = self.driver.find_element(
                    By.CSS_SELECTOR, ".about-company, .company-info"
                ).text
                
                # Use AI to extract HR email
                ai_service = GroqAIService(api_key=self.config.groq_api_key)
                email_info = ai_service.extract_hr_email(company_info)
                
                if email_info.get("emails"):
                    job.hr_email = email_info["emails"][0]
                elif email_info.get("suggested_emails"):
                    job.hr_email = email_info["suggested_emails"][0]
                    
            except:
                logger.debug(f"Could not extract HR email for {job.company}")
            
        except Exception as e:
            logger.error(f"Failed to extract details for {job.title}: {e}")
        
        return job

# ===== APPLICATION MANAGER =====
class ApplicationManager:
    def __init__(self, config: Config, driver: webdriver.Chrome, 
                 resume_manager: ResumeManager, email_manager: EmailManager):
        self.config = config
        self.driver = driver
        self.wait = WebDriverWait(driver, 15)
        self.resume_manager = resume_manager
        self.email_manager = email_manager
        self.ai_service = GroqAIService(api_key=config.groq_api_key)
        self.applied_jobs = []
        self.failed_jobs = []
        
        # Load previous applications
        self._load_application_history()
    
    def _load_application_history(self):
        """Load previously applied jobs"""
        history_file = "application_history.json"
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    self.applied_jobs = json.load(f)
            except:
                self.applied_jobs = []
    
    def _save_application_history(self):
        """Save application history"""
        history_file = "application_history.json"
        with open(history_file, 'w') as f:
            json.dump(self.applied_jobs, f, indent=2)

    def _write_job_bible_record(self, job: Job, applied: bool, reason: Optional[str] = None) -> None:
        """Write an auditable per-job record."""
        try:
            out_dir = os.path.join("bible", str(job.id))
            os.makedirs(out_dir, exist_ok=True)
            record = {
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "url": job.url,
                "source": job.source,
                "jd_hash": job.jd_hash,
                "applied": applied,
                "applied_date": job.applied_date,
                "status": job.status,
                "ats_score_before": job.ats_score_before,
                "ats_score_after": job.ats_score_after,
                "ats_score": job.ats_score,
                "custom_resume_path": job.custom_resume_path,
                "hr_email": job.hr_email,
                "reason": reason,
            }
            with open(os.path.join(out_dir, "record.json"), "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write job bible record for {job.id}: {e}")
    
    def apply_to_job(self, job: Job) -> bool:
        """Apply to a single job with all features"""
        logger.info(f"Applying to: {job.title} at {job.company}")
        
        try:
            # Step 1: Check if already applied
            if self._is_already_applied(job):
                logger.info(f"Already applied to {job.title}")
                return False
            
            # Step 2: Calculate ATS score (before tailoring)
            job.ats_score_before = self.resume_manager.calculate_ats_score(job.description)
            logger.info(f"ATS Score (before) for {job.title}: {job.ats_score_before:.1f}")

            job.ats_score_after = job.ats_score_before
            
            # Tailor resume only if below target.
            if job.ats_score_before < self.config.ats_target_score:
                logger.warning(f"ATS score {job.ats_score_before:.1f} below target. Customizing resume...")

                custom_resume_path = f"custom_resumes/resume_{job.id}.pdf"
                os.makedirs("custom_resumes", exist_ok=True)

                job.custom_resume_path = self.resume_manager.customize_for_jd(
                    job.description, custom_resume_path
                )

                tailored = self.resume_manager.last_customized_resume
                if tailored:
                    job.ats_score_after = self.resume_manager.calculate_ats_score(
                        job.description, resume=tailored
                    )

            job.ats_score = job.ats_score_after

            # If the tailored (updated) resume still doesn't meet the minimum threshold, skip.
            if job.ats_score_after is not None and job.ats_score_after < self.config.min_ats_to_apply:
                logger.warning(
                    f"Skipping application for {job.title} - ATS (after) {job.ats_score_after:.1f} below min {self.config.min_ats_to_apply}."
                )
                self.failed_jobs.append(job)
                self._write_job_bible_record(job, applied=False, reason="ats_after_below_min")
                return False
            
            # Step 3: Apply via platform
            application_success = self._apply_via_platform(job)
            
            if application_success:
                job.applied = True
                job.applied_date = datetime.now().strftime("%Y-%m-%d")
                job.status = ApplicationStatus.APPLIED.value
                
                # Step 4: Send email to HR if available
                if job.hr_email:
                    cover_letter = self.ai_service.generate_cover_letter(
                        job.title, job.company, self.resume_manager.resume.summary if self.resume_manager.resume else '', self.resume_manager.resume.skills if self.resume_manager.resume else [], job.description
                    )
                    
                    email_sent = self.email_manager.send_hr_email(
                        job, self.resume_manager.resume, cover_letter
                    )
                    
                    if email_sent:
                        logger.info(f"HR email sent for {job.title}")
                
                # Step 5: Save to history
                self.applied_jobs.append({
                    "id": job.id,
                    "title": job.title,
                    "company": job.company,
                    "applied_date": job.applied_date,
                    "ats_score_before": job.ats_score_before,
                    "ats_score_after": job.ats_score_after,
                    "ats_score": job.ats_score,
                    "hr_email_sent": bool(job.hr_email)
                })
                
                self._save_application_history()
                self._write_job_bible_record(job, applied=True)
                logger.info(f"Successfully applied to {job.title}")
                
                return True
            else:
                self.failed_jobs.append(job)
                self._write_job_bible_record(job, applied=False, reason="application_platform_failed")
                return False
                
        except Exception as e:
            logger.error(f"Application failed for {job.title}: {e}")
            self.failed_jobs.append(job)
            self._write_job_bible_record(job, applied=False, reason=str(e))
            return False
    
    def _is_already_applied(self, job: Job) -> bool:
        """Check if job was already applied to"""
        for applied_job in self.applied_jobs:
            if applied_job.get("id") == job.id:
                return True
        return False
    
    def _apply_via_platform(self, job: Job) -> bool:
        """Apply via the job platform (Naukri, LinkedIn, etc.)"""
        self.driver.get(job.url)
        time.sleep(3)
        
        try:
            # Check various apply button selectors
            apply_selectors = [
                "//button[contains(text(), 'Apply')]",
                "//a[contains(text(), 'Apply')]",
                "//button[text()='Apply']",
                "//span[text()='Apply']/parent::button"
            ]
            
            apply_button = None
            for selector in apply_selectors:
                try:
                    if "//" in selector:
                        apply_button = self.driver.find_element(By.XPATH, selector)
                    else:
                        apply_button = self.driver.find_element(By.CSS_SELECTOR, selector)
                    
                    if apply_button and apply_button.is_displayed():
                        break
                except:
                    continue
            
            if not apply_button:
                logger.warning(f"No apply button found for {job.title}")
                return False
            
            # Click apply button
            self.driver.execute_script("arguments[0].click();", apply_button)
            time.sleep(2)
            
            # Handle application questions
            return self._handle_application_questions(job)
            
        except Exception as e:
            logger.error(f"Platform application failed: {e}")
            return False
    
    def _handle_application_questions(self, job: Job) -> bool:
        """Handle application form questions"""
        max_attempts = 10
        attempts = 0
        
        while attempts < max_attempts:
            attempts += 1
            
            try:
                # Check for success message
                success_selectors = [
                    "//div[contains(text(), 'successfully applied')]",
                    "//span[contains(text(), 'application submitted')]",
                    "//*[contains(text(), 'Thank you for applying')]"
                ]
                
                for selector in success_selectors:
                    try:
                        if "//" in selector:
                            elements = self.driver.find_elements(By.XPATH, selector)
                        else:
                            elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        
                        if elements and any("success" in e.text.lower() or 
                                          "thank" in e.text.lower() for e in elements):
                            return True
                    except:
                        continue
                
                # Check for questions
                question_types = self._detect_question_type()
                
                if not question_types:
                    # No questions found, might be done
                    time.sleep(2)
                    continue
                
                # Answer questions
                for q_type in question_types:
                    if not self._answer_question(job, q_type):
                        logger.warning(f"Failed to answer {q_type} question")
                        return False
                
                # Click next/submit
                self._click_next_button()
                time.sleep(2)
                
            except Exception as e:
                logger.debug(f"Question handling attempt {attempts} failed: {e}")
        
        return False
    
    def _detect_question_type(self) -> List[str]:
        """Detect type of questions on page"""
        question_types = []
        
        # Check for radio buttons (multiple choice)
        radio_buttons = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        if radio_buttons:
            question_types.append("radio")
        
        # Check for text inputs
        text_inputs = self.driver.find_elements(By.CSS_SELECTOR, "textarea, input[type='text']")
        if text_inputs:
            question_types.append("text")
        
        # Check for dropdowns
        dropdowns = self.driver.find_elements(By.CSS_SELECTOR, "select")
        if dropdowns:
            question_types.append("dropdown")
        
        # Check for file upload
        file_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        if file_inputs:
            question_types.append("file")
        
        return question_types
    
    def _answer_question(self, job: Job, q_type: str) -> bool:
        """Answer question based on type"""
        try:
            if q_type == "radio":
                # Select first radio button (simplified)
                radio_button = self.driver.find_element(
                    By.CSS_SELECTOR, "input[type='radio']"
                )
                radio_button.click()
                
            elif q_type == "text":
                # Find text area and answer using AI
                text_area = self.driver.find_element(By.CSS_SELECTOR, "textarea")
                question_text = text_area.get_attribute("placeholder") or ""
                
                if question_text:
                    answer = self.ai_service.answer_application_question(
                        question_text, self.resume_manager.resume.raw_text if self.resume_manager.resume else ''
                    )
                    text_area.send_keys(answer[:500])
            
            elif q_type == "dropdown":
                # Select first option
                dropdown = self.driver.find_element(By.CSS_SELECTOR, "select")
                options = dropdown.find_elements(By.TAG_NAME, "option")
                if len(options) > 1:
                    options[1].click()  # Skip first empty option
            
            elif q_type == "file":
                # Upload resume if file input found
                file_input = self.driver.find_element(By.CSS_SELECTOR, "input[type='file']")
                resume_path = job.custom_resume_path or self.resume_manager.config.data.get("naukri", {}).get(
                    "custom_resume_path", "resume.pdf"
                )
                if os.path.exists(resume_path):
                    file_input.send_keys(os.path.abspath(resume_path))
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to answer {q_type} question: {e}")
            return False
    
    def _click_next_button(self):
        """Click next/submit button"""
        next_selectors = [
            "//button[contains(text(), 'Next')]",
            "//button[contains(text(), 'Submit')]",
            "//button[contains(text(), 'Save')]",
            "//button[text()='Continue']"
        ]
        
        for selector in next_selectors:
            try:
                if "//" in selector:
                    button = self.driver.find_element(By.XPATH, selector)
                else:
                    button = self.driver.find_element(By.CSS_SELECTOR, selector)
                
                if button.is_enabled():
                    self.driver.execute_script("arguments[0].click();", button)
                    return True
            except:
                continue
        
        return False

# ===== DASHBOARD & ANALYTICS =====
class JobDashboard:
    def __init__(self):
        self.stats_file = "application_stats.json"
        self.stats = self._load_stats()
    
    def _load_stats(self) -> Dict:
        """Load application statistics"""
        if os.path.exists(self.stats_file):
            with open(self.stats_file, 'r') as f:
                return json.load(f)
        return {
            "total_applied": 0,
            "successful": 0,
            "failed": 0,
            "interview_calls": 0,
            "offers": 0,
            "ats_scores": [],
            "daily_applications": {}
        }
    
    def update_stats(self, application_success: bool, ats_score: float = None):
        """Update application statistics"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        self.stats["total_applied"] += 1
        
        if application_success:
            self.stats["successful"] += 1
        else:
            self.stats["failed"] += 1
        
        if ats_score:
            self.stats["ats_scores"].append(ats_score)
        
        if today in self.stats["daily_applications"]:
            self.stats["daily_applications"][today] += 1
        else:
            self.stats["daily_applications"][today] = 1
        
        self._save_stats()
    
    def _save_stats(self):
        """Save statistics to file"""
        with open(self.stats_file, 'w') as f:
            json.dump(self.stats, f, indent=2)
    
    def generate_report(self) -> str:
        """Generate analytics report"""
        report = []
        report.append("=" * 50)
        report.append("JOB APPLICATION ANALYTICS REPORT")
        report.append("=" * 50)
        report.append(f"\nTotal Applications: {self.stats['total_applied']}")
        report.append(f"Successful: {self.stats['successful']}")
        report.append(f"Failed: {self.stats['failed']}")
        report.append(f"Success Rate: {(self.stats['successful']/self.stats['total_applied']*100):.1f}%" 
                     if self.stats['total_applied'] > 0 else "Success Rate: 0%")
        
        if self.stats['ats_scores']:
            avg_ats = sum(self.stats['ats_scores']) / len(self.stats['ats_scores'])
            report.append(f"\nAverage ATS Score: {avg_ats:.1f}")
            report.append(f"Highest ATS Score: {max(self.stats['ats_scores']):.1f}")
            report.append(f"Lowest ATS Score: {min(self.stats['ats_scores']):.1f}")
        
        # Daily applications trend
        if self.stats['daily_applications']:
            report.append("\nDaily Applications Trend:")
            for date, count in sorted(self.stats['daily_applications'].items())[-7:]:
                report.append(f"  {date}: {count} applications")
        
        report.append("\n" + "=" * 50)
        
        return "\n".join(report)

# ===== N8N INTEGRATION =====
class N8NIntegration:
    """Integration with n8n workflow automation"""
    
    @staticmethod
    def trigger_workflow(workflow_name: str, data: Dict):
        """Trigger n8n workflow via webhook"""
        webhook_url = f"http://localhost:5678/webhook/{workflow_name}"
        
        try:
            response = requests.post(webhook_url, json=data, timeout=10)
            if response.status_code == 200:
                logger.info(f"Triggered n8n workflow: {workflow_name}")
                return True
        except Exception as e:
            logger.error(f"Failed to trigger n8n workflow: {e}")
        
        return False
    
    @staticmethod
    def create_application_workflow(job: Job):
        """Create n8n workflow for job application automation"""
        workflow = {
            "name": f"Job Application - {job.company}",
            "nodes": [
                {
                    "name": "Start",
                    "type": "n8n-nodes-base.start",
                    "position": [250, 300]
                },
                {
                    "name": "Extract Job Details",
                    "type": "n8n-nodes-base.function",
                    "position": [450, 300],
                    "parameters": {
                        "jsCode": f"""
// Extract job details
const jobDetails = {{
    title: "{job.title}",
    company: "{job.company}",
    url: "{job.url}",
    description: "{job.description[:500]}"
}};
return [{{json: jobDetails}}];
                        """
                    }
                },
                {
                    "name": "Customize Resume",
                    "type": "n8n-nodes-base.httpRequest",
                    "position": [650, 300],
                    "parameters": {
                        "url": "http://localhost:8000/customize-resume",
                        "requestMethod": "POST"
                    }
                }
            ],
            "connections": {
                "Start": {
                    "main": [[{"node": "Extract Job Details", "type": "main", "index": 0}]]
                },
                "Extract Job Details": {
                    "main": [[{"node": "Customize Resume", "type": "main", "index": 0}]]
                }
            }
        }
        
        # Save workflow
        workflow_file = f"n8n_workflows/{job.id}.json"
        os.makedirs("n8n_workflows", exist_ok=True)
        
        with open(workflow_file, 'w') as f:
            json.dump(workflow, f, indent=2)
        
        logger.info(f"Created n8n workflow: {workflow_file}")
        return workflow_file

# ===== MAIN APPLICATION =====
class JobApplicationAutomation:
    """Main class orchestrating the entire job application process"""
    
    def __init__(self, config_path: str = "config.yaml"):
        # Load configuration
        self.config = Config(config_path)
        
        # Setup browser
        self.driver = self._setup_browser()
        
        # Initialize managers
        self.resume_manager = ResumeManager(self.config)
        self.email_manager = EmailManager(self.config)
        self.job_scraper = JobScraper(self.config, self.driver)
        self.application_manager = ApplicationManager(
            self.config, self.driver, self.resume_manager, self.email_manager
        )
        self.dashboard = JobDashboard()
        self.n8n = N8NIntegration()
        
        logger.info("Job Application Automation System Initialized")
    
    def _setup_browser(self) -> webdriver.Chrome:
        """Setup Chrome browser with optimal settings"""
        return create_browser()
    
    def run_full_automation(self):
        """Run complete job application automation"""
        logger.info("Starting full automation pipeline")
        
        try:
            # Step 1: Generate LaTeX resume
            logger.info("Generating LaTeX resume...")
            latex_pdf = self.resume_manager.generate_latex_resume()
            if latex_pdf:
                logger.info(f"LaTeX resume generated: {latex_pdf}")
            
            # Step 1.5: Login to Naukri
            logger.info("Logging into Naukri...")
            self.job_scraper._login_naukri()

            # Step 2: Scrape jobs from multiple sources
            logger.info("Scraping jobs...")
            jobs = []
            
            # Scrape from Naukri
            naukri_jobs = self.job_scraper.scrape_naukri()
            jobs.extend(naukri_jobs)
            
            # Scrape from LinkedIn (optional)
            # linkedin_jobs = self.job_scraper.scrape_linkedin()
            # jobs.extend(linkedin_jobs)
            
            logger.info(f"Total jobs found: {len(jobs)}")
            
            # Step 3: Extract detailed information for each job
            detailed_jobs = []
            for job in jobs[:self.config.max_applications]:
                detailed_job = self.job_scraper.extract_job_details(job)
                detailed_jobs.append(detailed_job)
                time.sleep(1)  # Be respectful
            
            # Step 4: Filter and prioritize jobs
            prioritized_jobs = self._prioritize_jobs(detailed_jobs)
            
            # Step 5: Apply to jobs
            successful_applications = 0
            
            for job in prioritized_jobs:
                if successful_applications >= self.config.max_applications:
                    break
                
                # Calculate ATS score
                ats_score = self.resume_manager.calculate_ats_score(job.description)
                logger.info(f"ATS Score for {job.title}: {ats_score:.1f}")
                
                success = self.application_manager.apply_to_job(job)

                # Update dashboard (prefer after-tailoring ATS score when available)
                ats_for_stats = job.ats_score_after if job.ats_score_after is not None else ats_score
                self.dashboard.update_stats(success, ats_for_stats)

                if success:
                    successful_applications += 1
                    # Create n8n workflow for follow-ups
                    self.n8n.create_application_workflow(job)

                # Delay between applications (both successes and failures)
                time.sleep(random.uniform(10, 30))
            
            # Step 6: Generate report
            self._generate_final_report(successful_applications)
            
        except KeyboardInterrupt:
            logger.info("Process interrupted by user")
        except Exception as e:
            logger.error(f"Automation failed: {e}", exc_info=True)
        finally:
            self.cleanup()
    
    def _prioritize_jobs(self, jobs: List[Job]) -> List[Job]:
        """Prioritize jobs based on multiple factors"""
        
        def priority_score(job: Job) -> float:
            score = 0.0
            
            # Score based on title relevance
            title_keywords = ["senior", "lead", "principal", "architect"]
            for keyword in title_keywords:
                if keyword in job.title.lower():
                    score += 10
            
            # Score based on company size (simplified)
            large_companies = ["google", "microsoft", "amazon", "meta", "apple"]
            if any(company in job.company.lower() for company in large_companies):
                score += 20
            
            # Score based on location match
            if self.config.location.lower() in job.location.lower():
                score += 15
            
            # Score based on HR email availability
            if job.hr_email:
                score += 5
            
            return score
        
        # Sort jobs by priority score
        jobs.sort(key=priority_score, reverse=True)
        return jobs
    
    def _generate_final_report(self, successful_applications: int):
        """Generate and save final report"""
        # Dashboard report
        dashboard_report = self.dashboard.generate_report()
        print("\n" + dashboard_report)
        
        # Save to file
        report_file = f"reports/report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        os.makedirs("reports", exist_ok=True)
        
        with open(report_file, 'w') as f:
            f.write(dashboard_report)
        
        # Save failed jobs
        failed_jobs = self.application_manager.failed_jobs
        if failed_jobs:
            failed_file = "failed_jobs.json"
            with open(failed_file, 'w') as f:
                json.dump([job.__dict__ for job in failed_jobs], f, indent=2)
            logger.info(f"Saved {len(failed_jobs)} failed jobs to {failed_file}")
        
        # Send email report
        self._send_daily_report(successful_applications)
    
    def _send_daily_report(self, successful_applications: int):
        """Send daily report email"""
        report_body = f"""
Daily Job Application Report
Date: {datetime.now().strftime('%Y-%m-%d')}

Applications Submitted: {successful_applications}
Total Applications (All Time): {self.dashboard.stats['total_applied']}

Failed Applications: {len(self.application_manager.failed_jobs)}

Top 5 Jobs Applied Today:
{self._get_today_top_jobs()}

Best Regards,
Job Application Bot
        """
        
        # Send to yourself
        self.email_manager._send_simple_email(
            self.config.sender_email,
            f"Job Application Report - {datetime.now().strftime('%Y-%m-%d')}",
            report_body
        )
    
    def _get_today_top_jobs(self) -> str:
        """Get today's top applied jobs"""
        today = datetime.now().strftime("%Y-%m-%d")
        today_jobs = []
        
        for job in self.application_manager.applied_jobs[-5:]:
            if job.get("applied_date", "").startswith(today):
                today_jobs.append(f"- {job['title']} at {job['company']}")
        
        return "\n".join(today_jobs) if today_jobs else "No applications today"
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            self.driver.quit()
            logger.info("Browser closed")
        except:
            pass
        
        # Save final state
        self.dashboard._save_stats()
        self.application_manager._save_application_history()

# ===== FASTAPI SERVER (Optional) =====
from fastapi import FastAPI, HTTPException
import uvicorn
from pydantic import BaseModel

app = FastAPI(title="Job Application API")

class JobApplicationRequest(BaseModel):
    job_url: str
    custom_resume: bool = True
    send_hr_email: bool = True

@app.post("/apply")
async def apply_to_job(request: JobApplicationRequest):
    """API endpoint to apply to a job"""
    # This would integrate with the ApplicationManager
    return {"status": "processing", "job_url": request.job_url}

@app.get("/stats")
async def get_statistics():
    """Get application statistics"""
    dashboard = JobDashboard()
    return dashboard.stats

@app.post("/generate-resume")
async def generate_resume(job_description: str = ""):
    """Generate customized resume"""
    # Implementation would use ResumeManager
    return {"status": "generated", "resume_path": "resume_custom.pdf"}

def run_api_server():
    """Run the FastAPI server"""
    uvicorn.run(app, host="0.0.0.0", port=8000)

# ===== COMMAND LINE INTERFACE =====
import argparse

def main():
    parser = argparse.ArgumentParser(description="Job Application Automation System")
    parser.add_argument("--mode", choices=["full", "scrape", "apply", "resume", "dashboard", "api"],
                       default="full", help="Operation mode")
    parser.add_argument("--config", default="config.yaml", help="Configuration file path")
    parser.add_argument("--max-jobs", type=int, default=10, help="Maximum jobs to process")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    
    args = parser.parse_args()
    
    # Update config if needed
    if args.max_jobs != parser.get_default('max_jobs'):
        with open(args.config, 'r') as f:
            config_data = yaml.safe_load(f)
        if "naukri" in config_data:
            config_data["naukri"]["max_applications"] = args.max_jobs
            with open(args.config, 'w') as f:
                yaml.dump(config_data, f)
    
    # Create automation system
    automation = JobApplicationAutomation(args.config)
    
    if args.mode == "full":
        automation.run_full_automation()
    elif args.mode == "scrape":
        jobs = automation.job_scraper.scrape_naukri()
        print(f"Scraped {len(jobs)} jobs")
    elif args.mode == "dashboard":
        print(automation.dashboard.generate_report())
    elif args.mode == "api":
        run_api_server()
    else:
        print(f"Mode {args.mode} not implemented yet")

if __name__ == "__main__":
    main()