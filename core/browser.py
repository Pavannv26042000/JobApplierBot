"""
Browser setup utilities for JobApplierBot.
Anti-detection Chrome configuration shared between bots.
"""

from __future__ import annotations

import logging
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)


def create_browser(headless: bool = False,
                   user_agent: Optional[str] = None,
                   proxy: Optional[str] = None) -> webdriver.Chrome:
    """
    Create a Chrome browser with anti-detection settings.

    Args:
        headless: Run in headless mode (no visible window).
        user_agent: Custom user agent string.
        proxy: Proxy server URL (e.g., "http://proxy:8080").

    Returns:
        Configured Chrome WebDriver instance.
    """
    options = Options()

    # --- Window ---
    options.add_argument("--start-maximized")
    options.add_argument("--window-size=1920,1080")

    if headless:
        options.add_argument("--headless=new")

    # --- Anti-Detection ---
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # --- Stability ---
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-webrtc")
    options.add_argument("--disable-features=WebRtcHideLocalIpsWithMdns")

    # --- Notifications ---
    prefs = {
        "profile.default_content_setting_values.notifications": 2,
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
    }
    options.add_experimental_option("prefs", prefs)

    # --- Proxy ---
    if proxy:
        options.add_argument(f"--proxy-server={proxy}")

    # --- Custom User Agent ---
    ua = user_agent or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # --- Create Driver ---
    driver = webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=options,
    )

    # CDP evasion
    driver.execute_cdp_cmd("Network.setUserAgentOverride", {"userAgent": ua})
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    logger.info("Browser initialized with anti-detection settings")
    return driver


def random_delay(min_sec: float = 1.0, max_sec: float = 3.0) -> None:
    """Sleep for a random duration to appear human-like."""
    import random
    import time
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)


def human_type(element, text: str, min_delay: float = 0.05, max_delay: float = 0.15) -> None:
    """Type text into an element letter-by-letter with randomized human keypress timing."""
    import random
    import time
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(min_delay, max_delay))


def human_scroll(driver, distance: int = 500, steps: int = 5) -> None:
    """Scroll down the page gradually with random micro-pauses to simulate human reading."""
    import random
    import time
    step_size = distance // steps
    for _ in range(steps):
        driver.execute_script(f"window.scrollBy(0, {step_size + random.randint(-20, 20)});")
        time.sleep(random.uniform(0.1, 0.4))
