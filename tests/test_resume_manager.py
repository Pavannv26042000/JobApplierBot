"""Tests for the resume manager."""

import json
import os
import tempfile

import pytest

from core.resume_manager import ResumeManager, ResumeData


class TestResumeDataCreation:
    """Test ResumeData dataclass."""

    def test_default_values(self):
        rd = ResumeData()
        assert rd.name == ""
        assert rd.skills == []
        assert rd.raw_text == ""

    def test_custom_values(self):
        rd = ResumeData(
            name="John Doe",
            email="john@example.com",
            skills=["Python", "Java"],
        )
        assert rd.name == "John Doe"
        assert len(rd.skills) == 2


class TestTextParsing:
    """Test resume text parsing."""

    def setup_method(self):
        self.manager = ResumeManager()

    def test_parse_name_from_first_line(self):
        text = "John Doe\njohn@example.com\nSummary\nExperienced developer"
        resume = self.manager._parse_text(text)
        assert resume.name == "John Doe"

    def test_parse_email(self):
        text = "John Doe\nEmail: john.doe@example.com\nPhone: 1234567890"
        resume = self.manager._parse_text(text)
        assert resume.email == "john.doe@example.com"

    def test_parse_phone(self):
        text = "John Doe\nPhone: +91 7899569686"
        resume = self.manager._parse_text(text)
        assert "7899569686" in resume.phone

    def test_parse_skills_section(self):
        text = "John Doe\nSkills\nPython, Java, Go, SQL\nReact, Node.js"
        resume = self.manager._parse_text(text)
        assert "Python" in resume.skills
        assert "Java" in resume.skills

    def test_parse_summary_section(self):
        text = "John Doe\nSummary\nExperienced software developer with 5 years"
        resume = self.manager._parse_text(text)
        assert "Experienced" in resume.summary

    def test_empty_text(self):
        resume = self.manager._parse_text("")
        assert resume.name == ""
        assert resume.raw_text == ""


class TestJsonParsing:
    """Test JSON resume format parsing."""

    def test_parse_json_resume(self):
        resume_data = {
            "name": "Pavan NV",
            "contact": {"email": "pavan@example.com", "phone": "+91 7899569686"},
            "skills": {"languages": ["Java", "Go"], "frameworks": ["Spring Boot"]},
            "experience": [{"title": "SWE", "company": "Acme"}],
            "education": [{"degree": "B.E.", "institution": "SVCE"}],
            "projects": [{"name": "SonarApp", "description": "Real-time sonar"}],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(resume_data, f)
            path = f.name

        try:
            manager = ResumeManager()
            resume = manager._parse_json(path)
            assert resume.name == "Pavan NV"
            assert resume.email == "pavan@example.com"
            assert "Java" in resume.skills
            assert "Spring Boot" in resume.skills
        finally:
            os.unlink(path)


class TestResumeTailoring:
    """Test resume tailoring functionality."""

    def setup_method(self):
        self.manager = ResumeManager()
        self.manager.resume = ResumeData(
            name="Test User",
            skills=["Python", "Java"],
            summary="Experienced developer",
            raw_text="Test User\nSkills: Python, Java\nExperience: 5 years",
        )

    def test_tailoring_adds_keywords(self):
        tailored = self.manager.tailor_for_jd(
            "Need Django and Flask developer",
            missing_keywords=["Django", "Flask", "REST APIs"],
        )
        assert "Django" in tailored.skills
        assert "Flask" in tailored.skills
        assert "REST APIs" in tailored.skills
        # Original skills preserved
        assert "Python" in tailored.skills
        assert "Java" in tailored.skills

    def test_tailoring_no_duplicates(self):
        tailored = self.manager.tailor_for_jd(
            "Need Python developer",
            missing_keywords=["Python", "python", "PYTHON"],
        )
        python_count = sum(1 for s in tailored.skills if s.lower() == "python")
        assert python_count == 1

    def test_tailoring_limits_keywords(self):
        many_keywords = [f"Keyword{i}" for i in range(50)]
        tailored = self.manager.tailor_for_jd("job desc", missing_keywords=many_keywords)
        # Should cap at 25 + existing 2
        assert len(tailored.skills) <= 27

    def test_tailoring_adds_suggestion_to_summary(self):
        tailored = self.manager.tailor_for_jd(
            "job desc",
            missing_keywords=[],
            suggestions=["Strong background in microservices architecture"],
        )
        assert "microservices" in tailored.summary.lower()

    def test_tailoring_preserves_original(self):
        self.manager.tailor_for_jd("job desc", missing_keywords=["NewSkill"])
        # Original resume should be unchanged
        assert "NewSkill" not in self.manager.resume.skills


class TestPDFGeneration:
    """Test PDF generation."""

    def test_generate_simple_pdf(self):
        manager = ResumeManager()
        resume = ResumeData(
            name="Test User",
            email="test@example.com",
            phone="1234567890",
            summary="Test summary",
            skills=["Python", "Java"],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "test_resume.pdf")
            manager._generate_simple_pdf(resume, output)
            assert os.path.exists(output)
            assert os.path.getsize(output) > 0


class TestResumeRawTextBuilding:
    """Test raw text building for ATS scoring."""

    def test_build_includes_all_sections(self):
        manager = ResumeManager()
        resume = ResumeData(
            name="John",
            email="john@test.com",
            skills=["Python"],
            experience=[{"title": "SWE", "company": "Google", "responsibilities": ["Built APIs"]}],
            education=[{"degree": "BS CS", "institution": "MIT"}],
        )
        text = manager._build_raw_text(resume)
        assert "John" in text
        assert "Python" in text
        assert "SWE" in text
        assert "Google" in text
        assert "Built APIs" in text
        assert "BS CS" in text
        assert "MIT" in text
