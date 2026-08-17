"""Tests for the configuration loader."""

import os
import tempfile

import pytest
import yaml

from core.config import load_config, AppConfig


class TestDefaultConfig:
    """Test configuration with defaults only."""

    def test_load_without_file(self):
        config = load_config(config_path=None)
        assert isinstance(config, AppConfig)
        assert config.groq.model == "llama-3.3-70b-versatile"
        assert config.ats.target_score == 80
        assert config.ats.min_to_apply == 60

    def test_load_nonexistent_file(self):
        config = load_config(config_path="/nonexistent/config.yaml")
        assert isinstance(config, AppConfig)


class TestYAMLConfig:
    """Test loading from YAML files."""

    def setup_method(self):
        self._env_backup = dict(os.environ)
        for k in ["GROQ_API_KEY", "LINKEDIN_USERNAME", "LINKEDIN_PASSWORD", 
                  "NAUKRI_EMAIL", "NAUKRI_PASSWORD", "RESUME_PATH", "COVER_LETTER_PATH"]:
            os.environ.pop(k, None)

    def teardown_method(self):
        os.environ.clear()
        os.environ.update(self._env_backup)

    def _write_config(self, data: dict) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml.dump(data, f)
        f.close()
        return f.name

    def test_load_groq_config(self):
        path = self._write_config({
            "groq": {"api_key": "test_key", "model": "llama-3.1-8b-instant"}
        })
        try:
            config = load_config(path)
            assert config.groq.api_key == "test_key"
            assert config.groq.model == "llama-3.1-8b-instant"
        finally:
            os.unlink(path)

    def test_load_ats_config(self):
        path = self._write_config({
            "ats": {"target_score": 90, "min_to_apply": 70}
        })
        try:
            config = load_config(path)
            assert config.ats.target_score == 90
            assert config.ats.min_to_apply == 70
        finally:
            os.unlink(path)

    def test_load_linkedin_config(self):
        path = self._write_config({
            "positions": ["Software Engineer", "Java Developer"],
            "locations": ["Bengaluru", "Remote"],
            "username": "test@example.com",
            "password": "testpass",
            "phone_number": "1234567890",
            "salary": "100,000",
        })
        try:
            config = load_config(path)
            assert config.linkedin.username == "test@example.com"
            assert len(config.linkedin.positions) == 2
            assert "Bengaluru" in config.linkedin.locations
            assert config.linkedin.salary == "100,000"
        finally:
            os.unlink(path)

    def test_load_naukri_config(self):
        path = self._write_config({
            "naukri": {
                "email": "test@naukri.com",
                "role": "Backend Developer",
                "location": "Mumbai",
                "max_applications": 20,
            }
        })
        try:
            config = load_config(path)
            assert config.naukri.email == "test@naukri.com"
            assert config.naukri.role == "Backend Developer"
            assert config.naukri.max_applications == 20
        finally:
            os.unlink(path)

    def test_load_uploads_format(self):
        path = self._write_config({
            "uploads": {
                "Resume": "/path/to/resume.pdf",
                "Cover Letter": "/path/to/cover.pdf",
            }
        })
        try:
            config = load_config(path)
            assert config.linkedin.resume_path == "/path/to/resume.pdf"
            assert config.linkedin.cover_letter_path == "/path/to/cover.pdf"
        finally:
            os.unlink(path)


class TestEnvOverrides:
    """Test that environment variables override YAML values."""

    def test_groq_key_from_env(self):
        os.environ["GROQ_API_KEY"] = "env_groq_key"
        try:
            config = load_config(config_path=None)
            assert config.groq.api_key == "env_groq_key"
        finally:
            del os.environ["GROQ_API_KEY"]

    def test_linkedin_from_env(self):
        os.environ["LINKEDIN_USERNAME"] = "env_user"
        os.environ["LINKEDIN_PASSWORD"] = "env_pass"
        try:
            config = load_config(config_path=None)
            assert config.linkedin.username == "env_user"
            assert config.linkedin.password == "env_pass"
        finally:
            del os.environ["LINKEDIN_USERNAME"]
            del os.environ["LINKEDIN_PASSWORD"]

    def test_env_overrides_yaml(self):
        path = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml.dump({"groq": {"api_key": "yaml_key"}}, path)
        path.close()

        os.environ["GROQ_API_KEY"] = "env_key_wins"
        try:
            config = load_config(path.name)
            assert config.groq.api_key == "env_key_wins"
        finally:
            del os.environ["GROQ_API_KEY"]
            os.unlink(path.name)
