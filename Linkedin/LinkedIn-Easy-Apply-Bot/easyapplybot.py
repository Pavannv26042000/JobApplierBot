from __future__ import annotations

import json
import csv
import logging
import os
import random
import re
import time
from datetime import datetime, timedelta
import getpass
from pathlib import Path

import pandas as pd
import pyautogui
import yaml
from bs4 import BeautifulSoup
from PyPDF2 import PdfReader
from fpdf import FPDF
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from core.ai_service import GroqAIService
from core.ats_scorer import ATSScorer
from core.resume_manager import ResumeManager as CoreResumeManager
from core.question_answerer import QuestionAnswerer
from core.browser import create_browser
from core.job_deduplicator import JobDeduplicator
from core.config import load_config
from core.notifier import Notifier, EmailNotifier

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
# ChromeDriverManager = ChromeDriverManager.ChromeDriverManager


log = logging.getLogger(__name__)


def setupLogger() -> None:
    dt: str = datetime.strftime(datetime.now(), "%m_%d_%y %H_%M_%S ")

    if not os.path.isdir('./logs'):
        os.mkdir('./logs')

    # TODO need to check if there is a log dir available or not
    logging.basicConfig(filename=('./logs/' + str(dt) + 'applyJobs.log'), filemode='w',
                        format='%(asctime)s::%(name)s::%(levelname)s::%(message)s', datefmt='./logs/%d-%b-%y %H:%M:%S')
    log.setLevel(logging.DEBUG)
    c_handler = logging.StreamHandler()
    c_handler.setLevel(logging.DEBUG)
    c_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%H:%M:%S')
    c_handler.setFormatter(c_format)
    log.addHandler(c_handler)


class EasyApplyBot:
    setupLogger()
    # MAX_SEARCH_TIME is 10 hours by default, feel free to modify it
    MAX_SEARCH_TIME = 60 * 60

    def __init__(self,
                 username,
                 password,
                 phone_number,
                 # profile_path,
                 salary,
                 rate,
                 groq_api_key: str = "",
                 groq_model: str = "llama3-70b-8192",
                 ats_target_score: int = 80,
                 min_ats_to_apply: int = 60,
                 tailor_resume: bool = True,
                 referral_enabled: bool = False,
                 referral_max_contacts: int = 3,
                 uploads={},
                 filename='output.csv',
                 blacklist=[],
                 blackListTitles=[],
                 experience_level=[]
                 ) -> None:

        log.info("Welcome to Easy Apply Bot")
        dirpath: str = os.getcwd()
        log.info("current directory is : " + dirpath)
        log.info("Please wait while we prepare the bot for you")
        if experience_level:
            experience_levels = {
                1: "Entry level",
                2: "Associate",
                3: "Mid-Senior level",
                4: "Director",
                5: "Executive",
                6: "Internship"
            }
            applied_levels = [experience_levels[level] for level in experience_level]
            log.info("Applying for experience level roles: " + ", ".join(applied_levels))
        else:
            log.info("Applying for all experience levels")
        

        self.uploads = uploads
        self.original_resume_path = self.uploads.get("Resume")
        self.salary = salary
        self.rate = rate
        # self.profile_path = profile_path
        past_ids: list | None = self.get_appliedIDs(filename)
        self.appliedJobIDs: list = past_ids if past_ids != None else []
        self.filename: str = filename
        self.options = self.browser_options()
        self.browser = create_browser()
        self.wait = WebDriverWait(self.browser, 30)
        self.blacklist = blacklist
        self.blackListTitles = blackListTitles
        self.start_linkedin(username, password)
        self.phone_number = phone_number
        self.experience_level = experience_level

        # Tailoring + ATS + AI agent config
        self.groq_api_key = groq_api_key
        self.ats_target_score = ats_target_score
        self.min_ats_to_apply = min_ats_to_apply
        self.tailor_resume = tailor_resume
        self.referral_enabled = referral_enabled
        self.referral_max_contacts = referral_max_contacts

        self.ai_service = GroqAIService(api_key=groq_api_key, model=groq_model)
        self.ats_scorer = ATSScorer()
        self.deduplicator = JobDeduplicator()

        # Load resume text once for AI + ATS scoring.
        self.resume_text = self._load_resume_text(self.uploads.get("Resume"))
        self.resume_text = (self.resume_text or "")[:12000]
        self.current_jd_text = ""
        self.question_answerer = QuestionAnswerer(ai_service=self.ai_service, qa_file='qa.csv', resume_text=self.resume_text, salary=self.salary)


        self.locator = {
            "next": (By.CSS_SELECTOR, "button[aria-label='Continue to next step']"),
            "review": (By.CSS_SELECTOR, "button[aria-label='Review your application']"),
            "submit": (By.CSS_SELECTOR, "button[aria-label='Submit application']"),
            "error": (By.CLASS_NAME, "artdeco-inline-feedback__message"),
            "upload_resume": (By.XPATH, "//*[contains(@id, 'jobs-document-upload-file-input-upload-resume')]"),
            "upload_cv": (By.XPATH, "//*[contains(@id, 'jobs-document-upload-file-input-upload-cover-letter')]"),
            "follow": (By.CSS_SELECTOR, "label[for='follow-company-checkbox']"),
            "upload": (By.NAME, "file"),
            "search": (By.CLASS_NAME, "jobs-search-results-list"),
            "links": ("xpath", '//div[@data-job-id]'),
            "fields": (By.CLASS_NAME, "jobs-easy-apply-form-section__grouping"),
            "radio_select": (By.CSS_SELECTOR, "input[type='radio']"), #need to append [value={}].format(answer)
            "multi_select": (By.XPATH, "//*[contains(@id, 'text-entity-list-form-component')]"),
            "text_select": (By.CLASS_NAME, "artdeco-text-input--input"),
            "2fa_oneClick": (By.ID, 'reset-password-submit-button'),
            "easy_apply_button": (By.XPATH, '//button[contains(@class, "jobs-apply-button")]')

        }

        #initialize questions and answers file
        self.qa_file = Path("qa.csv")
        self.answers = {}

        #if qa file does not exist, create it
        if self.qa_file.is_file():
            df = pd.read_csv(self.qa_file)
            for index, row in df.iterrows():
                self.answers[str(row['Question']).lower()] = row['Answer']
        #if qa file does exist, load it
        else:
            df = pd.DataFrame(columns=["Question", "Answer"])
            df.to_csv(self.qa_file, index=False, encoding='utf-8')


    def get_appliedIDs(self, filename) -> list | None:
        try:
            df = pd.read_csv(filename,
                             header=None,
                             names=['timestamp', 'jobID', 'job', 'company', 'attempted', 'result'],
                             lineterminator='\n',
                             encoding='utf-8')

            df['timestamp'] = pd.to_datetime(df['timestamp'], format="%Y-%m-%d %H:%M:%S")
            df = df[df['timestamp'] > (datetime.now() - timedelta(days=2))]
            jobIDs: list = list(df.jobID)
            log.info(f"{len(jobIDs)} jobIDs found")
            return jobIDs
        except Exception as e:
            log.info(str(e) + "   jobIDs could not be loaded from CSV {}".format(filename))
            return None

    def browser_options(self):
        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument('--no-sandbox')
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-blink-features")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-webrtc")
        options.add_argument("--disable-features=WebRtcHideLocalIpsWithMdns")
        return options

    def start_linkedin(self, username, password) -> None:
        log.info("Logging in.....Please wait :)  ")
        self.browser.get("https://www.linkedin.com/login")
        try:
            # Wait for page to load
            WebDriverWait(self.browser, 10).until(
                EC.presence_of_element_located((By.ID, "username"))
            )
            
            # Fill credentials
            user_field = self.browser.find_element(By.ID, "username")
            pw_field = self.browser.find_element(By.ID, "password")
            
            user_field.send_keys(username)
            time.sleep(1)
            pw_field.send_keys(password)
            time.sleep(2)
            
            # Find login button by text content
            login_button = self.browser.find_element(
                By.XPATH, 
                "//button[contains(., 'Sign in') and @type='submit']"
            )
            login_button.click()
            
            # Handle possible 2FA
            time.sleep(10)
            if "checkpoint/challenge" in self.browser.current_url:
                log.info("2FA required - please complete authentication manually")
                time.sleep(30)  # Give time to complete 2FA
            else:
                log.info("Login successful")
            
        except Exception as e:
            log.error(f"Login failed: {str(e)}")
            # Capture screenshot for debugging
            self.browser.save_screenshot("login_error.png")
            log.info("Screenshot saved as login_error.png")

    def fill_data(self) -> None:
        self.browser.set_window_size(1, 1)
        self.browser.set_window_position(2000, 2000)

    def start_apply(self, positions, locations) -> None:
        start: float = time.time()
        self.fill_data()
        self.positions = positions
        self.locations = locations
        combos: list = []
        while len(combos) < len(positions) * len(locations):
            position = positions[random.randint(0, len(positions) - 1)]
            location = locations[random.randint(0, len(locations) - 1)]
            combo: tuple = (position, location)
            if combo not in combos:
                combos.append(combo)
                log.info(f"Applying to {position}: {location}")
                location = "&location=" + location
                self.applications_loop(position, location)
            if len(combos) > 500:
                break

    # self.finish_apply() --> this does seem to cause more harm than good, since it closes the browser which we usually don't want, other conditions will stop the loop and just break out

    def applications_loop(self, position, location):

        count_application = 0
        count_job = 0
        jobs_per_page = 0
        start_time: float = time.time()

        log.info("Looking for jobs.. Please wait..")

        self.browser.set_window_position(1, 1)
        self.browser.maximize_window()
        self.browser, _ = self.next_jobs_page(position, location, jobs_per_page, experience_level=self.experience_level)
        log.info("Looking for jobs.. Please wait..")

        while time.time() - start_time < self.MAX_SEARCH_TIME:
            try:
                log.info(f"{(self.MAX_SEARCH_TIME - (time.time() - start_time)) // 60} minutes left in this search")

                # sleep to make sure everything loads, add random to make us look human.
                randoTime: float = random.uniform(1.5, 2.9)
                log.debug(f"Sleeping for {round(randoTime, 1)}")
                #time.sleep(randoTime)
                self.load_page(sleep=0.5)

                # LinkedIn displays the search results in a scrollable <div> on the left side, we have to scroll to its bottom

                # scroll to bottom

                if self.is_present(self.locator["search"]):
                    scrollresults = self.get_elements("search")
                    #     self.browser.find_element(By.CLASS_NAME,
                    #     "jobs-search-results-list"
                    # )
                    # Selenium only detects visible elements; if we scroll to the bottom too fast, only 8-9 results will be loaded into IDs list
                    for i in range(300, 3000, 100):
                        self.browser.execute_script("arguments[0].scrollTo(0, {})".format(i), scrollresults[0])
                    scrollresults = self.get_elements("search")
                    #time.sleep(1)

                # get job links, (the following are actually the job card objects)
                if self.is_present(self.locator["links"]):
                    links = self.get_elements("links")
                # links = self.browser.find_elements("xpath",
                #     '//div[@data-job-id]'
                # )

                    jobIDs = {} #{Job id: processed_status}
                
                    # children selector is the container of the job cards on the left
                    for link in links:
                            if 'Applied' not in link.text: #checking if applied already
                                if link.text not in self.blacklist: #checking if blacklisted
                                    jobID = link.get_attribute("data-job-id")
                                    if jobID == "search":
                                        log.debug("Job ID not found, search keyword found instead? {}".format(link.text))
                                        continue
                                    else:
                                        jobIDs[jobID] = "To be processed"
                    if len(jobIDs) > 0:
                        self.apply_loop(jobIDs)
                    self.browser, jobs_per_page = self.next_jobs_page(position,
                                                                      location,
                                                                      jobs_per_page, 
                                                                      experience_level=self.experience_level)
                else:
                    self.browser, jobs_per_page = self.next_jobs_page(position,
                                                                      location,
                                                                      jobs_per_page, 
                                                                      experience_level=self.experience_level)


            except Exception as e:
                print(e)
    def apply_loop(self, jobIDs):
        for jobID in jobIDs:
            if jobIDs[jobID] == "To be processed":
                applied = self.apply_to_job(jobID)
                if applied:
                    log.info(f"Applied to {jobID}")
                else:
                    log.info(f"Failed to apply to {jobID}")
                jobIDs[jobID] = applied

    def apply_to_job(self, jobID):
        # #self.avoid_lock() # annoying

        # get job page
        self.get_job_page(jobID)

        # let page load
        time.sleep(1)

        # Extract job description text + (optionally) tailor resume for ATS fit.
        self.current_jd_text = self.extract_job_description()
        if self.tailor_resume:
            tailored_resume_path = self.prepare_tailored_resume_for_job(jobID, self.current_jd_text)
            if tailored_resume_path is None:
                log.info(f"Skipping {jobID}: ATS too low after tailoring.")
                self.write_to_file(False, jobID, self.browser.title, False)
                return False
            if tailored_resume_path:
                self.uploads["Resume"] = tailored_resume_path

        # get easy apply button
        button = self.get_easy_apply_button()


        # word filter to skip positions not wanted
        if button is not False:
            if any(word in self.browser.title for word in self.blackListTitles):
                log.info('skipping this application, a blacklisted keyword was found in the job position')
                string_easy = "* Contains blacklisted keyword"
                result = False
            else:
                string_easy = "* has Easy Apply Button"
                log.info("Clicking the EASY apply button")
                button.click()
                clicked = True
                time.sleep(1)
                self.fill_out_fields()
                result: bool = self.send_resume()
                if result:
                    string_easy = "*Applied: Sent Resume"
                    self.try_connect_and_request_referral(jobID)
                else:
                    string_easy = "*Did not apply: Failed to send Resume"
        elif "You applied on" in self.browser.page_source:
            log.info("You have already applied to this position.")
            string_easy = "* Already Applied"
            result = False
        else:
            log.info("The Easy apply button does not exist.")
            string_easy = "* Doesn't have Easy Apply Button"
            result = False


        # position_number: str = str(count_job + jobs_per_page)
        log.info(f"\nPosition {jobID}:\n {self.browser.title} \n {string_easy} \n")

        self.write_to_file(button, jobID, self.browser.title, result)
        return result

    def write_to_file(self, button, jobID, browserTitle, result) -> None:
        def re_extract(text, pattern):
            target = re.search(pattern, text)
            if target:
                target = target.group(1)
            return target

        timestamp: str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        attempted: bool = False if button == False else True
        job = re_extract(browserTitle.split(' | ')[0], r"\(?\d?\)?\s?(\w.*)")
        company = re_extract(browserTitle.split(' | ')[1], r"(\w.*)")

        toWrite: list = [timestamp, jobID, job, company, attempted, result]
        with open(self.filename, 'a+') as f:
            writer = csv.writer(f)
            writer.writerow(toWrite)

    @staticmethod
    def _parse_json_from_text(text: str) -> dict:
        """Best-effort JSON parsing from LLM output."""
        return GroqAIService._parse_json_from_text(text)

    def _load_resume_text(self, resume_path: str | None) -> str:
        if not resume_path or not os.path.exists(resume_path):
            log.warning(f"Resume path not found: {resume_path}")
            return ""
        if resume_path.lower().endswith(".pdf"):
            reader = PdfReader(resume_path)
            parts: list[str] = []
            for page in reader.pages:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:
                    continue
            return "\n".join(parts).strip()
        # Fallback: we only auto-tailor from PDF for now.
        log.warning("Only PDF resume auto-tailoring is supported right now.")
        return ""

    def extract_job_description(self) -> str:
        """Extract job description text from the current LinkedIn job page."""
        try:
            soup = BeautifulSoup(self.browser.page_source, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            text = soup.get_text(" ", strip=True)
            # Cap size to keep prompt size reasonable.
            return text[:6000]
        except Exception as e:
            log.error(f"Failed to extract job description: {e}")
            return ""

    def calculate_ats_score_from_text(self, resume_text: str, job_description: str) -> float:
        """Lightweight ATS score based on keyword overlap + section presence."""
        return self.ats_scorer.calculate_score(resume_text, job_description)

    def _generate_pdf_from_text(self, text: str, output_pdf_path: str) -> None:
        Path(output_pdf_path).parent.mkdir(parents=True, exist_ok=True)
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Helvetica", size=10)
        epw = pdf.epw
        for line in (text or "").splitlines():
            pdf.x = pdf.l_margin
            pdf.multi_cell(epw, 5, line.strip() if line.strip() else " ", new_x="LMARGIN", new_y="NEXT")
        pdf.output(output_pdf_path)

    def analyze_jd_for_tailoring(self, job_description: str) -> list[str]:
        """Use LLM to find missing skills/keywords for the current JD."""
        return self.ai_service.get_missing_keywords(self.resume_text, job_description)

    def prepare_tailored_resume_for_job(self, job_id: str, job_description: str) -> str | None:
        if not self.tailor_resume:
            return self.original_resume_path

        if not self.resume_text or not job_description:
            return self.original_resume_path

        ats_before = self.calculate_ats_score_from_text(self.resume_text, job_description)
        if ats_before >= self.ats_target_score:
            # Still keep the original resume; it is already "good enough".
            return self.original_resume_path

        missing_keywords = self.analyze_jd_for_tailoring(job_description)
        tailored_text = (self.resume_text or "").strip()
        tailored_text += "\n\nSkills: " + ", ".join(missing_keywords[:25])

        ats_after = self.calculate_ats_score_from_text(tailored_text, job_description)
        if ats_after < self.min_ats_to_apply:
            log.warning(f"Skipping {job_id}: ATS after tailoring {ats_after:.1f} below min {self.min_ats_to_apply}")
            return None

        output_pdf_path = str(Path("tailored_resumes") / f"resume_{job_id}.pdf")
        self._generate_pdf_from_text(tailored_text, output_pdf_path)
        return output_pdf_path

    def llm_answer_application_question(self, question: str) -> str:
        """Answer a form question using the resume (+ current JD when available)."""
        return self.ai_service.answer_application_question(question, self.resume_text, self.current_jd_text)

    def try_connect_and_request_referral(self, jobID: str) -> bool:
        """Best-effort referral request after a successful application.

        This is intentionally conservative: it only tries a few profiles and swallows most failures.
        """
        if not self.referral_enabled:
            return False

        try:
            page_title = self.browser.title or ""
            # Heuristic parsing of "Job Title at Company | LinkedIn Jobs"
            job_title = page_title.split(" at ")[0].strip() if " at " in page_title else page_title
            company = ""
            if " at " in page_title:
                company = page_title.split(" at ", 1)[1].split(" | ")[0].strip()

            # Extract a company slug from the HTML.
            m = re.search(r"/company/([a-zA-Z0-9-]+)/", self.browser.page_source or "")
            if not m:
                return False
            company_slug = m.group(1)

            people_url = f"https://www.linkedin.com/company/{company_slug}/people/"
            self.browser.get(people_url)
            time.sleep(3)

            # Scroll to load people cards.
            for _ in range(3):
                self.browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)

            connect_buttons = self.browser.find_elements(By.XPATH, "//button[contains(., 'Connect')]")
            if not connect_buttons:
                return False

            note_message = (
                f"Hi! I'm interested in the {job_title} role at {company or 'your company'}. "
                f"If you think I'd be a fit, could you share a referral? Thanks!"
            )

            connect_buttons[0].click()
            time.sleep(2)

            # Click “Add a note” if present
            try:
                add_note_btn = self.browser.find_element(By.XPATH, "//button[contains(., 'Add a note')]")
                add_note_btn.click()
                time.sleep(1)
            except Exception:
                pass

            # Fill note
            try:
                textarea = self.browser.find_element(By.XPATH, "//textarea")
                textarea.clear()
                textarea.send_keys(note_message)
            except Exception:
                return False

            # Send
            try:
                send_btn = self.browser.find_element(By.XPATH, "//button[contains(., 'Send')]")
                send_btn.click()
            except Exception:
                # Note sent UI may differ; treat as best-effort.
                pass

            return True
        except Exception as e:
            log.error(f"Referral request failed for {jobID}: {e}")
            return False

    def get_job_page(self, jobID):

        job: str = 'https://www.linkedin.com/jobs/view/' + str(jobID)
        self.browser.get(job)
        self.job_page = self.load_page(sleep=0.5)
        return self.job_page

    def get_easy_apply_button(self):
        EasyApplyButton = False
        try:
            buttons = self.get_elements("easy_apply_button")
            # buttons = self.browser.find_elements("xpath",
            #     '//button[contains(@class, "jobs-apply-button")]'
            # )
            for button in buttons:
                if "Easy Apply" in button.text:
                    EasyApplyButton = button
                    self.wait.until(EC.element_to_be_clickable(EasyApplyButton))
                else:
                    log.debug("Easy Apply button not found")
            
        except Exception as e: 
            print("Exception:",e)
            log.debug("Easy Apply button not found")


        return EasyApplyButton

    def fill_out_fields(self):
        fields = self.browser.find_elements(By.CLASS_NAME, "jobs-easy-apply-form-section__grouping")
        for field in fields:

            if "Mobile phone number" in field.text:
                field_input = field.find_element(By.TAG_NAME, "input")
                field_input.clear()
                field_input.send_keys(self.phone_number)


        return


    def get_elements(self, type) -> list:
        elements = []
        element = self.locator[type]
        if self.is_present(element):
            elements = self.browser.find_elements(element[0], element[1])
        return elements

    def is_present(self, locator):
        return len(self.browser.find_elements(locator[0],
                                              locator[1])) > 0

    def send_resume(self) -> bool:
        def is_present(button_locator) -> bool:
            return len(self.browser.find_elements(button_locator[0],
                                                  button_locator[1])) > 0

        try:
            #time.sleep(random.uniform(1.5, 2.5))
            next_locator = (By.CSS_SELECTOR,
                            "button[aria-label='Continue to next step']")
            review_locator = (By.CSS_SELECTOR,
                              "button[aria-label='Review your application']")
            submit_locator = (By.CSS_SELECTOR,
                              "button[aria-label='Submit application']")
            error_locator = (By.CLASS_NAME,"artdeco-inline-feedback__message")
            upload_resume_locator = (By.XPATH, '//span[text()="Upload resume"]')
            upload_cv_locator = (By.XPATH, '//span[text()="Upload cover letter"]')
            # WebElement upload_locator = self.browser.find_element(By.NAME, "file")
            follow_locator = (By.CSS_SELECTOR, "label[for='follow-company-checkbox']")

            submitted = False
            loop = 0
            while loop < 2:
                time.sleep(1)
                # Upload resume
                if is_present(upload_resume_locator):
                    #upload_locator = self.browser.find_element(By.NAME, "file")
                    try:
                        resume_locator = self.browser.find_element(By.XPATH, "//*[contains(@id, 'jobs-document-upload-file-input-upload-resume')]")
                        resume = self.uploads["Resume"]
                        resume_locator.send_keys(resume)
                    except Exception as e:
                        log.error(e)
                        log.error("Resume upload failed")
                        log.debug("Resume: " + resume)
                        log.debug("Resume Locator: " + str(resume_locator))
                # Upload cover letter if possible
                if is_present(upload_cv_locator):
                    cv = self.uploads["Cover Letter"]
                    cv_locator = self.browser.find_element(By.XPATH, "//*[contains(@id, 'jobs-document-upload-file-input-upload-cover-letter')]")
                    cv_locator.send_keys(cv)

                    #time.sleep(random.uniform(4.5, 6.5))
                elif len(self.get_elements("follow")) > 0:
                    elements = self.get_elements("follow")
                    for element in elements:
                        button = self.wait.until(EC.element_to_be_clickable(element))
                        button.click()

                if len(self.get_elements("submit")) > 0:
                    elements = self.get_elements("submit")
                    for element in elements:
                        button = self.wait.until(EC.element_to_be_clickable(element))
                        button.click()
                        log.info("Application Submitted")
                        submitted = True
                        break

                elif len(self.get_elements("error")) > 0:
                    elements = self.get_elements("error")
                    if "application was sent" in self.browser.page_source:
                        log.info("Application Submitted")
                        submitted = True
                        break
                    elif len(elements) > 0:
                        while len(elements) > 0:
                            log.info("Please answer the questions, waiting 5 seconds...")
                            time.sleep(5)
                            elements = self.get_elements("error")

                            for element in elements:
                                self.process_questions()

                            if "application was sent" in self.browser.page_source:
                                log.info("Application Submitted")
                                submitted = True
                                break
                            elif is_present(self.locator["easy_apply_button"]):
                                log.info("Skipping application")
                                submitted = False
                                break
                        continue
                        #add explicit wait
                    
                    else:
                        log.info("Application not submitted")
                        time.sleep(2)
                        break
                    # self.process_questions()

                elif len(self.get_elements("next")) > 0:
                    elements = self.get_elements("next")
                    for element in elements:
                        button = self.wait.until(EC.element_to_be_clickable(element))
                        button.click()

                elif len(self.get_elements("review")) > 0:
                    elements = self.get_elements("review")
                    for element in elements:
                        button = self.wait.until(EC.element_to_be_clickable(element))
                        button.click()

                elif len(self.get_elements("follow")) > 0:
                    elements = self.get_elements("follow")
                    for element in elements:
                        button = self.wait.until(EC.element_to_be_clickable(element))
                        button.click()

        except Exception as e:
            log.error(e)
            log.error("cannot apply to this job")
            pass
            #raise (e)

        return submitted
    def process_questions(self):
        time.sleep(1)
        form = self.get_elements("fields") #self.browser.find_elements(By.CLASS_NAME, "jobs-easy-apply-form-section__grouping")
        for field in form:
            question = field.text
            answer = self.ans_question(question.lower())
            #radio button
            if self.is_present(self.locator["radio_select"]):
                try:
                    input = field.find_element(By.CSS_SELECTOR, "input[type='radio'][value={}]".format(answer))
                    input.execute_script("arguments[0].click();", input)
                except Exception as e:
                    log.error(e)
                    continue
            #multi select
            elif self.is_present(self.locator["multi_select"]):
                try:
                    input = field.find_element(self.locator["multi_select"])
                    input.send_keys(answer)
                except Exception as e:
                    log.error(e)
                    continue
            # text box
            elif self.is_present(self.locator["text_select"]):
                try:
                    input = field.find_element(self.locator["text_select"])
                    input.send_keys(answer)
                except Exception as e:
                    log.error(e)
                    continue



    def ans_question(self, question): #refactor this to an ans.yaml file
        # Prefer cached answers from qa.csv (stored as lowercase keys).
        if question in self.answers:
            return self.answers[question]

        answer = None
        if "how many" in question:
            answer = "1"
        elif "experience" in question:
            answer = "1"
        elif "sponsor" in question:
            answer = "No"
        elif 'do you ' in question:
            answer = "Yes"
        elif "have you " in question:
            answer = "Yes"
        elif "US citizen" in question:
            answer = "Yes"
        elif "are you " in question:
            answer = "Yes"
        elif "salary" in question:
            answer = self.salary
        elif "can you" in question:
            answer = "Yes"
        elif "gender" in question:
            answer = "Male"
        elif "race" in question:
            answer = "Wish not to answer"
        elif "lgbtq" in question:
            answer = "Wish not to answer"
        elif "ethnicity" in question:
            answer = "Wish not to answer"
        elif "nationality" in question:
            answer = "Wish not to answer"
        elif "government" in question:
            answer = "I do not wish to self-identify"
        elif "are you legally" in question:
            answer = "Yes"
        else:
            answer = self.question_answerer.answer(question, self.current_jd_text)
            if answer == "user provided":
                log.info("Not able to answer question automatically. Please provide answer")
                time.sleep(15)

            # df = pd.DataFrame(self.answers, index=[0])
            # df.to_csv(self.qa_file, encoding="utf-8")
        log.info("Answering question: " + question + " with answer: " + answer)

        # Append question and answer to the CSV
        if question not in self.answers:
            self.answers[question] = answer
            # Append a new question-answer pair to the CSV file
            new_data = pd.DataFrame({"Question": [question], "Answer": [answer]})
            new_data.to_csv(self.qa_file, mode='a', header=False, index=False, encoding='utf-8')
            log.info(f"Appended to QA file: '{question}' with answer: '{answer}'.")

        return answer

    def load_page(self, sleep=1):
        scroll_page = 0
        while scroll_page < 4000:
            self.browser.execute_script("window.scrollTo(0," + str(scroll_page) + " );")
            scroll_page += 500
            time.sleep(sleep)

        if sleep != 1:
            self.browser.execute_script("window.scrollTo(0,0);")
            time.sleep(sleep)

        # Use html.parser instead of lxml as fallback
        try:
            page = BeautifulSoup(self.browser.page_source, "lxml")
        except:
            page = BeautifulSoup(self.browser.page_source, "html.parser")
        return page

    def avoid_lock(self) -> None:
        x, _ = pyautogui.position()
        pyautogui.moveTo(x + 200, pyautogui.position().y, duration=1.0)
        pyautogui.moveTo(x, pyautogui.position().y, duration=0.5)
        pyautogui.keyDown('ctrl')
        pyautogui.press('esc')
        pyautogui.keyUp('ctrl')
        time.sleep(0.5)
        pyautogui.press('esc')

    def next_jobs_page(self, position, location, jobs_per_page, experience_level=[]):
        # Construct the experience level part of the URL
        experience_level_str = ",".join(map(str, experience_level)) if experience_level else ""
        experience_level_param = f"&f_E={experience_level_str}" if experience_level_str else ""
        self.browser.get(
            # URL for jobs page
            "https://www.linkedin.com/jobs/search/?f_LF=f_AL&keywords=" +
            position + location + "&start=" + str(jobs_per_page) + experience_level_param)
        #self.avoid_lock()
        log.info("Loading next job page?")
        self.load_page()
        return (self.browser, jobs_per_page)

    # def finish_apply(self) -> None:
    #     self.browser.close()


if __name__ == '__main__':

    with open("config.yaml", 'r') as stream:
        try:
            parameters = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            raise exc

    assert len(parameters['positions']) > 0
    assert len(parameters['locations']) > 0
    assert parameters['username'] is not None
    assert parameters['password'] is not None
    assert parameters['phone_number'] is not None


    if 'uploads' in parameters.keys() and type(parameters['uploads']) == list:
        raise Exception("uploads read from the config file appear to be in list format" +
                        " while should be dict. Try removing '-' from line containing" +
                        " filename & path")

    log.info({k: parameters[k] for k in parameters.keys() if k not in ['username', 'password']})

    output_filename: list = [f for f in parameters.get('output_filename', ['output.csv']) if f is not None]
    output_filename: list = output_filename[0] if len(output_filename) > 0 else 'output.csv'
    blacklist = parameters.get('blacklist', [])
    blackListTitles = parameters.get('blackListTitles', [])

    uploads = {} if parameters.get('uploads', {}) is None else parameters.get('uploads', {})
    for key in uploads.keys():
        assert uploads[key] is not None

    locations: list = [l for l in parameters['locations'] if l is not None]
    positions: list = [p for p in parameters['positions'] if p is not None]

    bot = EasyApplyBot(parameters['username'],
                       parameters['password'],
                       parameters['phone_number'],
                       parameters['salary'],
                       parameters['rate'], 
                       groq_api_key=parameters.get('groq', {}).get('api_key', os.getenv('GROQ_API_KEY', '')),
                       ats_target_score=parameters.get('ats', {}).get('target_score', 80),
                       min_ats_to_apply=parameters.get('ats', {}).get('min_to_apply', 60),
                       referral_enabled=parameters.get('referral', {}).get('enabled', False),
                       referral_max_contacts=parameters.get('referral', {}).get('max_contacts', 3),
                       uploads=uploads,
                       filename=output_filename,
                       blacklist=blacklist,
                       blackListTitles=blackListTitles,
                       experience_level=parameters.get('experience_level', [])
                       )
    bot.start_apply(positions, locations)


