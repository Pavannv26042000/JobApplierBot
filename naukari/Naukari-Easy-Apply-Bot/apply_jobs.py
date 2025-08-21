from selenium.webdriver.chrome.service import Service
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from gemini_api import bard_flash_response
from webdriver_manager.chrome import ChromeDriverManager
import time
import os
from pathlib import Path
import yaml

# === 1. Load Configuration ===
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

# Extract configurations
NAUKRI_CONFIG = config.get("naukri", {})
EMAIL = NAUKRI_CONFIG.get("email")
PASSWORD = NAUKRI_CONFIG.get("password")
ROLE = NAUKRI_CONFIG.get("role")
LOCATION = NAUKRI_CONFIG.get("location", "")
MAX_PAGES = NAUKRI_CONFIG.get("max_pages", 5)
MAX_APPLICATIONS = NAUKRI_CONFIG.get("max_applications", 10)
GEMINI_API_KEY = NAUKRI_CONFIG.get("gemini_api_key")

# Browser configuration
BROWSER_CONFIG = config.get("browser", {})
USE_DEFAULT_PROFILE = BROWSER_CONFIG.get("use_default_profile", False)
HEADLESS = BROWSER_CONFIG.get("headless", False)
WINDOW_SIZE = BROWSER_CONFIG.get("window_size", "1920,1080")

# === 2. Dynamic User Profile Path (Windows) ===
user = os.getlogin()
base_profile_path = Path(f"C:/Users/{user}/AppData/Local/Google/Chrome/User Data")

# === 3. Chrome Options ===
chrome_options = Options()
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option('useAutomationExtension', False)

if USE_DEFAULT_PROFILE:
    chrome_options.add_argument(f"user-data-dir={base_profile_path}")
    chrome_options.add_argument("profile-directory=Default")

if HEADLESS:
    chrome_options.add_argument("--headless=new")

chrome_options.add_argument(f"--window-size={WINDOW_SIZE}")

prefs = {
    "credentials_enable_service": False,
    "profile.password_manager_enabled": False
}
chrome_options.add_experimental_option("prefs", prefs)

# === 4. Auto-fetch ChromeDriver ===
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
wait = WebDriverWait(driver, 10)

# === 5. Confirm Browser Launch ===
driver.get("https://www.google.com")
print("Browser launched successfully with dynamic paths.")

# Initialize counters
applied = 0  # Count of jobs applied successfully
failed_job_links = []
failed = 0   # Count of jobs failed

def login_to_naukri():
    print("Logging into Naukri...")
    driver.get("https://www.naukri.com/mnjuser/login")
    
    try:
        print("Waiting for email input...")
        email_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Enter Email ID / Username']")))
        email_input.send_keys(EMAIL)
        print("Entered email.")

        password_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Enter Password']")))
        password_input.send_keys(PASSWORD)
        print("Entered password.")

        login_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[text()='Login']")))
        login_button.click()
        print("Clicked login button.")

        # Wait for a dashboard element that confirms successful login
        wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(@href, 'my-naukri')]")))
        print("Login successful.")

    except Exception as e:
        print(f"Login failed: {type(e).__name__}: {e}")
        input("If there's a CAPTCHA or other blocker, solve it in the browser and press Enter to continue...")

def search_jobs():
    """Search for job openings on Naukri.com and return job links"""
    job_links = []
    base_url = "https://www.naukri.com"
    
    for page in range(1, MAX_PAGES + 1):
        search_url = f"{base_url}/{ROLE.replace(' ', '-')}-jobs"
        if LOCATION:
            search_url += f"-in-{LOCATION.replace(' ', '-')}"
        if page > 1:
            search_url += f"-{page}"
        
        print(f"\nSearching page {page}: {search_url}")
        driver.get(search_url)
        time.sleep(3)

        # Handle CAPTCHA if any
        if "verify" in driver.current_url:
            input("CAPTCHA detected — solve it manually, then press Enter to continue...")
            time.sleep(2)

        try:
            # Updated job card structure
            job_cards = wait.until(
                EC.presence_of_all_elements_located((By.XPATH, "//div[contains(@class, 'srp-jobtuple-wrapper')]"))
            )
            
            if not job_cards:
                print("No job cards found. Structure may have changed.")
                continue
            
            for card in job_cards:
                try:
                    link = card.find_element(By.XPATH, ".//a[contains(@class, 'title')]").get_attribute("href")
                    if link and "job-listings" in link and link not in job_links:
                        job_links.append(link)
                except Exception as inner_e:
                    print(f"Skipping one job card due to error: {inner_e}")
            
            print(f"Found {len(job_cards)} jobs on page {page}")

        except Exception as e:
            print(f" Error extracting jobs: {type(e).__name__}: {e}")
        
        if len(job_links) >= MAX_APPLICATIONS:
            print(f" Reached job link cap ({MAX_APPLICATIONS}).")
            break

    return job_links

# Login
login_to_naukri()
# Get job listings
job_links = search_jobs()
print(f"Found {len(job_links)} jobs to apply for")

for job_url in job_links:
    if applied >= MAX_APPLICATIONS:
        print(f"Reached maximum applications ({MAX_APPLICATIONS})")
        break
        
    print(f"\nProcessing: {job_url}")
    driver.get(job_url)
    time.sleep(3)
    
    status = True
    try:
        # Check various job status indicators
        if driver.find_elements(By.ID, "already-applied"):
            print("Already applied to this position")
            continue
            
        alert_elements = driver.find_elements(By.XPATH, "//*[contains(@class, 'styles_alert-message-text__')]")
        if alert_elements:
            print("Job has alert message - skipping")
            failed += 1
            failed_job_links.append(job_url) 
            continue
            
        if driver.find_elements(By.ID, "company-site-button"):
            print("Application requires visiting company site - skipping")
            failed += 1
            failed_job_links.append(job_url) 
            continue
            
        if driver.find_elements(By.CLASS_NAME, "jdContainer"):
            print("Job container issue - skipping")
            failed += 1
            failed_job_links.append(job_url) 
            continue

    except Exception as e:
        print(f"Error checking job status: {e}")

    # Try to apply
    if applied < MAX_APPLICATIONS:
        try:
            # Click the Apply button
            apply_btn = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//*[text()='Apply']"))
            )
            apply_btn.click()
            time.sleep(2)

            # Check if application was immediately successful
            success_message = driver.find_elements(
                By.XPATH, "//span[contains(@class, 'apply-message') and contains(text(), 'successfully applied')]"
            )
            if success_message:
                print("Successfully applied.")
                applied += 1
                time.sleep(2)
                continue

        except Exception as e:
            print(f"Error during initial apply attempt: {e}")
        
        # Handle application questions
        while status and applied < MAX_APPLICATIONS:
            try:
                # Check for radio button questions
                radio_buttons = driver.find_elements(By.CSS_SELECTOR, ".ssrc__radio-btn-container")
                if radio_buttons:
                    question = driver.find_element(
                        By.XPATH, "//li[contains(@class, 'botItem')]/div/div/span"
                    ).text
                    print(question)

                    options = []
                    for index, button in enumerate(radio_buttons, start=1):
                        label = button.find_element(By.CSS_SELECTOR, "label")
                        value = button.find_element(By.CSS_SELECTOR, "input").get_attribute("value")
                        options.append(f"{index}. {label.text} (Value: {value})")
                        print(options[-1])

                    options_str = "\n".join(options)
                    user_input_message = f"{question}\n{options_str}"

                    selected_option = int(bard_flash_response(user_input_message, api_key=GEMINI_API_KEY))

                    selected_button = radio_buttons[selected_option - 1].find_element(By.CSS_SELECTOR, "input")
                    driver.execute_script("arguments[0].click();", selected_button)

                    save_button = wait.until(
                        EC.element_to_be_clickable((By.XPATH, "/html/body/div[2]/div/div[1]/div[3]/div/div"))
                    )
                    save_button.click()
                    time.sleep(1)
                    
                    # Check for success after answering
                    success_message = driver.find_elements(
                        By.XPATH, "//span[contains(@class, 'apply-message') and contains(text(), 'successfully applied')]"
                    )
                    if success_message:
                        print("Successfully applied after question.")
                        applied += 1
                        status = False
                    continue

                # Check for text input questions
                chat_list = driver.find_elements(By.XPATH, "//ul[contains(@id, 'chatList_')]")
                if chat_list:
                    li_elements = chat_list[0].find_elements(By.TAG_NAME, "li")
                    last_question_text = li_elements[-1].text if li_elements else ""
                    print("Last question text:", last_question_text)

                    response = bard_flash_response(last_question_text, api_key=GEMINI_API_KEY)
                    input_field = driver.find_element(By.XPATH, "//div[@class='textArea']")

                    # Special handling for date fields
                    if "Date of Birth" in last_question_text:
                        dob_field = driver.find_element(By.XPATH, "//input[contains(@id, 'dob')]")
                        dob_field.send_keys("01011990")
                    elif response:
                        input_field.send_keys(response)
                    else:
                        input_field.send_keys("None")
                    
                    time.sleep(1)

                    save_button = wait.until(
                        EC.element_to_be_clickable((By.XPATH, "/html/body/div[2]/div/div[1]/div[3]/div/div"))
                    )
                    save_button.click()
                    time.sleep(1)
                    
                    # Check for success after answering
                    success_message = driver.find_elements(
                        By.XPATH, "//span[contains(@class, 'apply-message') and contains(text(), 'successfully applied')]"
                    )
                    if success_message:
                        print("Successfully applied after question.")
                        applied += 1
                        status = False
                    continue
                
                # Final success check
                success_message = driver.find_elements(
                    By.XPATH, "//span[contains(@class, 'apply-message') and contains(text(), 'successfully applied')]"
                )
                if success_message:
                    print("Application successful.")
                    applied += 1
                    status = False
                else:
                    print("No more questions but application not confirmed")
                    status = False

            except Exception as e:
                print(f"Error during application process: {e}")
                status = False
                failed += 1

    # Add delay between applications
    time.sleep(5)

# Final report
print("\nApplication Summary:")
print(f"Successfully applied: {applied}")
print(f"Failed applications: {failed}")
print(f"Total jobs processed: {len(job_links)}")

if failed_job_links:
    with open("failed_jobs.txt", "w") as f:
        f.write("\n".join(failed_job_links))
    print(f"\n📝 Saved {len(failed_job_links)} failed job links to 'failed_jobs.txt'")

# Close the browser
driver.quit()
