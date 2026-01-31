from __future__ import annotations

import logging
import os
import time
import json
from pathlib import Path
from typing import List, Dict, Any
import yaml
import PyPDF2
import google.generativeai as genai
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# Setup logging
log = logging.getLogger(__name__)

def setup_logger() -> None:
    dt: str = time.strftime("%m_%d_%y_%H_%M_%S")
    if not os.path.isdir('./logs'):
        os.makedirs('./logs')
    logging.basicConfig(
        filename=f'./logs/{dt}_profile_optimizer.log',
        filemode='w',
        format='%(asctime)s::%(name)s::%(levelname)s::%(message)s',
        datefmt='%d-%b-%y %H:%M:%S'
    )
    log.setLevel(logging.DEBUG)
    c_handler = logging.StreamHandler()
    c_handler.setLevel(logging.DEBUG)
    c_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%H:%M:%S')
    c_handler.setFormatter(c_format)
    log.addHandler(c_handler)

class LinkedInProfileOptimizer:
    def __init__(self, config_path: str = "config.yaml") -> None:
        setup_logger()
        log.info("Initializing LinkedIn Profile Optimizer")
        
        # Load configuration
        with open(config_path, 'r') as stream:
            try:
                config = yaml.safe_load(stream)
            except yaml.YAMLError as exc:
                log.error(f"Failed to load config.yaml: {exc}")
                raise exc
        
        # Extract configurations from new structure
        linkedin_config = config.get('linkedin', {})
        browser_config = config.get('browser', {})
        
        self.username = linkedin_config.get('username')
        self.password = linkedin_config.get('password')
        self.resume_path = linkedin_config.get('resume_path')
        self.job_roles = linkedin_config.get('job_roles', [])
        self.gemini_api_key = linkedin_config.get('gemini_api_key')
        self.browser_config = browser_config
        
        # Validate required fields
        assert self.username, "Username is required in config.yaml"
        assert self.password, "Password is required in config.yaml"
        assert self.resume_path, "Resume path is required in config.yaml"
        assert self.job_roles, "At least one job role is required in config.yaml"
        assert self.gemini_api_key, "Gemini API key is required in config.yaml"
        
        # Initialize browser
        self.options = self.browser_options()
        self.browser = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=self.options)
        self.wait = WebDriverWait(self.browser, 30)
        
        # Extract resume text
        self.resume_text = self.extract_resume_text(self.resume_path)
        if not self.resume_text:
            log.warning("No text extracted from resume; Gemini responses may be limited")
        
        # Initialize Gemini API
        genai.configure(api_key=self.gemini_api_key)
        self.gemini_model = genai.GenerativeModel('gemini-2.5-flash')
        log.info("Gemini API initialized successfully")
        
        # Start LinkedIn login
        self.start_linkedin()

    def browser_options(self) -> Options:
        options = Options()
        options.add_argument("--start-maximized")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument('--no-sandbox')
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-webrtc")
        # Disable notifications
        options.add_argument("--disable-notifications")
        # Additional WebRTC suppression (from previous response)
        options.add_argument("--disable-rtc-smoothness-algorithm")
        options.add_argument("--disable-features=WebRtcHideLocalIpsWithMdns,WebRtcUseEchoCanceller3")
        options.add_argument("--webrtc-ip-handling-policy=disable_non_proxied_udp")
        if self.browser_config.get('headless', False):
            options.add_argument("--headless=new")
        options.add_argument(f"--window-size={self.browser_config.get('window_size', '1920,1080')}")
        if self.browser_config.get('use_default_profile', False):
            user = os.getlogin()
            base_profile_path = Path(f"C:/Users/{user}/AppData/Local/Google/Chrome/User Data")
            options.add_argument(f"user-data-dir={base_profile_path}")
            options.add_argument("profile-directory=Default")
        return options

    def extract_resume_text(self, pdf_path: str) -> str:
        try:
            text = ""
            with open(pdf_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                for page in reader.pages:
                    page_text = page.extract_text() or ""
                    text += page_text
            log.info("Resume text extracted successfully")
            return text
        except Exception as e:
            log.error(f"Failed to extract resume text: {e}")
            return ""

    def start_linkedin(self) -> None:
        log.info("Logging into LinkedIn...")
        self.browser.get("https://www.linkedin.com/login")
        try:
            # Wait for page to load
            WebDriverWait(self.browser, 10).until(
                EC.presence_of_element_located((By.ID, "username"))
            )
            user_field = self.browser.find_element(By.ID, "username")
            pw_field = self.browser.find_element(By.ID, "password")
            user_field.send_keys(self.username)
            time.sleep(1)
            pw_field.send_keys(self.password)
            time.sleep(2)
            login_button = self.browser.find_element(
                By.XPATH, "//button[contains(., 'Sign in') and @type='submit']"
            )
            login_button.click()
            time.sleep(10)
            if "checkpoint/challenge" in self.browser.current_url:
                log.info("2FA required - please complete authentication manually")
                input("Solve 2FA in the browser and press Enter to continue...")
            else:
                log.info("Login successful")
        except Exception as e:
            log.error(f"Login failed: {e}")
            self.browser.save_screenshot("login_error.png")
            log.info("Screenshot saved as login_error.png")
            raise

    def optimize_headline(self) -> bool:
        log.info("Optimizing profile headline")
        try:
            headline = self.generate_headline()
            self.browser.get("https://www.linkedin.com/in/me/edit/intro/")
            time.sleep(3)
            
            # Wait for and click the headline edit button
            edit_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(@aria-label, 'Edit headline')]"))
            )
            edit_button.click()
            time.sleep(1)
            
            # Find and update the headline input
            headline_input = self.wait.until(
                EC.presence_of_element_located((By.XPATH, "//input[contains(@id, 'headline')]"))
            )
            headline_input.clear()
            headline_input.send_keys(headline)
            
            # Save changes
            save_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Save')]"))
            )
            save_button.click()
            time.sleep(2)
            log.info(f"Headline updated: {headline}")
            return True
        except Exception as e:
            log.error(f"Failed to update headline: {e}")
            self.browser.save_screenshot("headline_error.png")
            return False

    def optimize_headline(self) -> bool:
        log.info("Optimizing profile headline")
        try:
            headline = self.generate_headline()
            self.browser.get("https://www.linkedin.com/in/me/edit/intro/")
            time.sleep(3)
            
            # Wait for and scroll to the headline edit button
            edit_button = self.wait.until(
                EC.presence_of_element_located((By.XPATH, "//button[contains(@aria-label, 'Edit headline')]"))
            )
            # Scroll the button into view
            self.browser.execute_script("arguments[0].scrollIntoView(true);", edit_button)
            time.sleep(1)
            
            # Click using JavaScript to avoid potential obstructions
            self.browser.execute_script("arguments[0].click();", edit_button)
            time.sleep(1)
            
            # Find and update the headline input
            headline_input = self.wait.until(
                EC.presence_of_element_located((By.XPATH, "//input[contains(@id, 'headline')]"))
            )
            headline_input.clear()
            headline_input.send_keys(headline)
            
            # Save changes
            save_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Save')]"))
            )
            save_button.click()
            time.sleep(2)
            log.info(f"Headline updated: {headline}")
            return True
        except Exception as e:
            log.error(f"Failed to update headline: {e}")
            self.browser.save_screenshot("headline_error.png")
            return False

    def optimize_skills(self) -> bool:
        log.info("Optimizing skills section")
        try:
            skills = self.generate_skills()
            self.browser.get("https://www.linkedin.com/in/me/edit/skills/")
            time.sleep(3)
            
            for skill in skills[:10]:  # Limit to 10 skills to avoid rate limits
                try:
                    # Click add skill button
                    add_skill_button = self.wait.until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Add skill')]"))
                    )
                    add_skill_button.click()
                    time.sleep(1)
                    
                    # Input skill
                    skill_input = self.wait.until(
                        EC.presence_of_element_located((By.XPATH, "//input[contains(@placeholder, 'Add a skill') or contains(@placeholder, 'Enter a skill')]"))
                    )
                    skill_input.clear()
                    skill_input.send_keys(skill)
                    time.sleep(1)
                    
                    # Select from dropdown if available
                    try:
                        skill_option = self.wait.until(
                            EC.element_to_be_clickable((By.XPATH, f"//div[contains(@class, 'basic-typeahead__selectable')]//span[contains(., '{skill}')]"))
                        )
                        skill_option.click()
                    except Exception:
                        # If no dropdown option, press Enter
                        skill_input.send_keys(Keys.ENTER)
                    
                    time.sleep(1)
                    log.info(f"Added skill: {skill}")
                except Exception as e:
                    log.warning(f"Failed to add skill {skill}: {e}")
                    continue
            
            # Save changes
            save_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Save')]"))
            )
            save_button.click()
            time.sleep(2)
            log.info("Skills section updated")
            return True
        except Exception as e:
            log.error(f"Failed to update skills section: {e}")
            self.browser.save_screenshot("skills_error.png")
            return False

    def optimize_experience(self) -> bool:
        log.info("Optimizing experience section")
        try:
            experiences = self.generate_experience()
            self.browser.get("https://www.linkedin.com/in/me/edit/experience/")
            time.sleep(3)
            
            for exp in experiences[:3]:  # Limit to 3 experiences
                try:
                    # Click add experience button
                    add_exp_button = self.wait.until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Add position')]"))
                    )
                    add_exp_button.click()
                    time.sleep(2)
                    
                    # Fill in experience details
                    title_input = self.wait.until(
                        EC.presence_of_element_located((By.XPATH, "//input[contains(@id, 'title')]"))
                    )
                    title_input.send_keys(exp.get("title", ""))
                    
                    company_input = self.browser.find_element(By.XPATH, "//input[contains(@id, 'company')]")
                    company_input.send_keys(exp.get("company", ""))
                    
                    # Save changes
                    save_button = self.wait.until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Save')]"))
                    )
                    save_button.click()
                    time.sleep(2)
                    log.info(f"Added experience: {exp.get('title')} at {exp.get('company')}")
                except Exception as e:
                    log.warning(f"Failed to add experience {exp.get('title')}: {e}")
                    continue
            
            log.info("Experience section updated")
            return True
        except Exception as e:
            log.error(f"Failed to update experience section: {e}")
            self.browser.save_screenshot("experience_error.png")
            return False

    def generate_headline(self) -> str:
        try:
            prompt = (
                f"Based on the resume:\n{self.resume_text}\n\n"
                f"Generate a concise LinkedIn headline (120 characters or less) for a professional targeting these roles: {', '.join(self.job_roles)}. "
                f"Include relevant keywords and make it impactful."
            )
            response = self.gemini_model.generate_content(prompt)
            headline = response.text.strip()[:120]
            return headline
        except Exception as e:
            log.error(f"Failed to generate headline: {e}")
            return f"{self.job_roles[0]} | Seeking Opportunities"

    def generate_about(self) -> str:
        try:
            prompt = (
                f"Based on the resume:\n{self.resume_text}\n\n"
                f"Write a professional LinkedIn About section (2000 characters or less) for a candidate targeting {', '.join(self.job_roles)}. "
                f"Highlight skills, experience, and achievements. Use a professional yet approachable tone."
            )
            response = self.gemini_model.generate_content(prompt)
            about = response.text.strip()[:2000]
            return about
        except Exception as e:
            log.error(f"Failed to generate about section: {e}")
            return "Professional seeking opportunities in " + ", ".join(self.job_roles)

    def generate_skills(self) -> list:
        try:
            prompt = (
                f"Based on the resume:\n{self.resume_text}\n\n"
                f"List exactly 10 relevant skills for a candidate targeting {', '.join(self.job_roles)}. "
                f"Return only the skill names, one per line, without any numbering or additional text."
            )
            response = self.gemini_model.generate_content(prompt)
            skills = [skill.strip() for skill in response.text.strip().split("\n") if skill.strip()]
            return skills[:10]
        except Exception as e:
            log.error(f"Failed to generate skills: {e}")
            return ["Python", "Java", "Software Development", "Project Management"]

    def generate_experience(self) -> list:
        try:
            prompt = (
                f"Based on the resume:\n{self.resume_text}\n\n"
                f"Generate up to 3 professional experience entries for a LinkedIn profile targeting {', '.join(self.job_roles)}. "
                f"Each entry should include: title, company, location, start_date (MM/YYYY), end_date (MM/YYYY or 'Present'), "
                f"and a description (200 characters or less). Return as a JSON list."
            )
            response = self.gemini_model.generate_content(prompt)
            try:
                experiences = json.loads(response.text.strip())
                return experiences[:3]
            except json.JSONDecodeError:
                log.warning("Failed to parse experience JSON, using fallback")
                return [
                    {"title": self.job_roles[0], "company": "Example Corp", "location": "Remote", 
                     "start_date": "01/2020", "end_date": "Present", "description": "Developed software solutions."}
                ]
        except Exception as e:
            log.error(f"Failed to generate experience: {e}")
            return [
                {"title": self.job_roles[0], "company": "Example Corp", "location": "Remote", 
                 "start_date": "01/2020", "end_date": "Present", "description": "Developed software solutions."}
            ]

    def optimize_profile(self) -> None:
        log.info("Starting LinkedIn profile optimization")
        success = {
            "headline": self.optimize_headline(),
            "about": self.optimize_about(),
            "skills": self.optimize_skills(),
            "experience": self.optimize_experience()
        }
        log.info("Profile optimization summary:")
        for section, status in success.items():
            log.info(f"{section.capitalize()}: {'Success' if status else 'Failed'}")
    
    def close(self) -> None:
        log.info("Closing browser")
        try:
            self.browser.quit()
        except Exception as e:
            log.error(f"Error closing browser: {e}")

if __name__ == '__main__':
    optimizer = None
    try:
        optimizer = LinkedInProfileOptimizer()
        optimizer.optimize_profile()
    except Exception as e:
        log.error(f"Optimization failed: {e}")
    finally:
        if optimizer:
            optimizer.close()