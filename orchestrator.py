"""
JobApplierBot Orchestrator
===========================
Unified CLI entry point for running LinkedIn and Naukri bots
from a single configuration.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import random
from datetime import datetime
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.config import load_config
from core.ai_service import GroqAIService
from core.ats_scorer import ATSScorer
from core.resume_manager import ResumeManager
from core.notifier import Notifier, EmailNotifier
from core.job_deduplicator import JobDeduplicator

logger = logging.getLogger("orchestrator")


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structured logging."""
    dt = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_dir / f"{dt}_orchestrator.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def run_linkedin(config, ai_service, dedup, notifier, dry_run=False):
    """Run the LinkedIn Easy Apply bot."""
    linkedin_dir = PROJECT_ROOT / "Linkedin" / "LinkedIn-Easy-Apply-Bot"
    sys.path.insert(0, str(linkedin_dir))
    bot = None

    try:
        # Import the LinkedIn bot
        os.chdir(linkedin_dir)
        from easyapplybot import EasyApplyBot

        if not config.linkedin.positions:
            logger.warning("No LinkedIn positions configured. Skipping LinkedIn.")
            return

        if not config.linkedin.username or not config.linkedin.password:
            logger.warning("LinkedIn credentials not set. Skipping LinkedIn.")
            return

        logger.info("=" * 50)
        logger.info("Starting LinkedIn Easy Apply Bot")
        logger.info(f"Positions: {config.linkedin.positions}")
        logger.info(f"Locations: {config.linkedin.locations}")
        logger.info("=" * 50)

        if dry_run:
            logger.info("[DRY RUN] Would start LinkedIn bot with above settings")
            return

        uploads = {}
        if config.linkedin.resume_path:
            uploads["Resume"] = config.linkedin.resume_path
        if config.linkedin.cover_letter_path:
            uploads["Cover Letter"] = config.linkedin.cover_letter_path

        bot = EasyApplyBot(
            username=config.linkedin.username,
            password=config.linkedin.password,
            phone_number=config.linkedin.phone_number,
            salary=config.linkedin.salary,
            rate=config.linkedin.rate,
            groq_api_key=config.groq.api_key,
            ats_target_score=config.ats.target_score,
            min_ats_to_apply=config.ats.min_to_apply,
            referral_enabled=config.linkedin.referral_enabled,
            referral_max_contacts=config.linkedin.referral_max_contacts,
            uploads=uploads,
            filename=config.linkedin.output_filename,
            blacklist=config.linkedin.blacklist,
            blackListTitles=config.linkedin.blacklist_titles,
            experience_level=config.linkedin.experience_level,
        )
        bot.start_apply(config.linkedin.positions, config.linkedin.locations)

    except KeyboardInterrupt:
        logger.warning("\n[Ctrl+C] Interrupted LinkedIn bot execution.")
        raise
    except ImportError as e:
        logger.error(f"Failed to import LinkedIn bot: {e}")
    except Exception as e:
        logger.error(f"LinkedIn bot failed: {e}", exc_info=True)
        notifier.notify("error", "LinkedIn Bot Failed", str(e))
    finally:
        if bot and hasattr(bot, "browser") and bot.browser:
            try:
                bot.browser.quit()
            except Exception:
                pass
        os.chdir(PROJECT_ROOT)


def run_naukri(config, ai_service, dedup, notifier, dry_run=False):
    """Run the Naukri Easy Apply bot."""
    naukri_dir = PROJECT_ROOT / "naukari" / "Naukari-Easy-Apply-Bot"
    sys.path.insert(0, str(naukri_dir))
    automation = None

    try:
        os.chdir(naukri_dir)
        from apply_jobs import JobApplicationAutomation

        if not config.naukri.email or not config.naukri.password:
            logger.warning("Naukri credentials not set. Skipping Naukri.")
            return

        logger.info("=" * 50)
        logger.info("Starting Naukri Easy Apply Bot")
        logger.info(f"Role: {config.naukri.role}")
        logger.info(f"Location: {config.naukri.location}")
        logger.info(f"Max applications: {config.naukri.max_applications}")
        logger.info("=" * 50)

        if dry_run:
            logger.info("[DRY RUN] Would start Naukri bot with above settings")
            return

        # The Naukri bot uses its own Config class internally
        automation = JobApplicationAutomation(config_path="Config.yaml")
        automation.run_full_automation()

    except KeyboardInterrupt:
        logger.warning("\n[Ctrl+C] Interrupted Naukri bot execution.")
        raise
    except ImportError as e:
        logger.error(f"Failed to import Naukri bot: {e}")
    except Exception as e:
        logger.error(f"Naukri bot failed: {e}", exc_info=True)
        notifier.notify("error", "Naukri Bot Failed", str(e))
    finally:
        if automation:
            try:
                automation.cleanup()
            except Exception:
                pass
        os.chdir(PROJECT_ROOT)


def run_dashboard(config):
    """Run the FastAPI dashboard server."""
    try:
        naukri_dir = PROJECT_ROOT / "naukari" / "Naukari-Easy-Apply-Bot"
        sys.path.insert(0, str(naukri_dir))
        os.chdir(naukri_dir)
        from apply_jobs import run_api_server
        logger.info("Starting dashboard API server on http://localhost:8000")
        run_api_server()
    except KeyboardInterrupt:
        logger.info("Dashboard server stopped by user.")
    except Exception as e:
        logger.error(f"Dashboard failed: {e}", exc_info=True)
    finally:
        os.chdir(PROJECT_ROOT)


def show_stats(config):
    """Display application statistics."""
    dedup = JobDeduplicator()
    stats = dedup.get_stats()

    print("\n" + "=" * 50)
    print("  JOB APPLICATION STATISTICS")
    print("=" * 50)
    print(f"\n  Total Jobs Tracked: {stats['total_tracked']}")
    print(f"  Applied: {stats['applied']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"\n  By Platform:")
    for platform, count in stats.get("by_platform", {}).items():
        print(f"    {platform}: {count}")
    print("\n" + "=" * 50)


def main():
    parser = argparse.ArgumentParser(
        description="JobApplierBot — Unified Job Application Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python orchestrator.py --platform both          # Run both LinkedIn and Naukri bots
  python orchestrator.py --platform linkedin       # LinkedIn only
  python orchestrator.py --platform naukri         # Naukri only
  python orchestrator.py --mode dashboard          # Start the web dashboard
  python orchestrator.py --mode stats              # Show application statistics
  python orchestrator.py --dry-run                 # Preview what would be done
        """,
    )
    parser.add_argument(
        "--platform",
        choices=["linkedin", "naukri", "both"],
        default="both",
        help="Which platform(s) to run (default: both)",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "scrape", "apply", "dashboard", "stats"],
        default="full",
        help="Operation mode (default: full)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config.yaml (default: auto-detect per platform)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without applying",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()
    setup_logging(args.log_level)

    # Load config
    config = load_config(args.config)

    # Initialize shared services
    ai_service = GroqAIService(
        api_key=config.groq.api_key,
        model=config.groq.model,
    )
    dedup = JobDeduplicator()

    # Setup notifier
    email_notifier = None
    if config.email.sender_email and config.email.sender_password:
        email_notifier = EmailNotifier(
            smtp_server=config.email.smtp_server,
            smtp_port=config.email.smtp_port,
            sender_email=config.email.sender_email,
            sender_password=config.email.sender_password,
        )
    notifier = Notifier(email_notifier=email_notifier)

    logger.info(f"JobApplierBot Orchestrator starting (platform={args.platform}, mode={args.mode})")
    if ai_service.is_available:
        logger.info(f"Groq AI service active (model: {config.groq.model})")
    else:
        logger.warning("Groq AI service not available — no API key configured")

    # Execute
    try:
        if args.mode == "dashboard":
            run_dashboard(config)
        elif args.mode == "stats":
            show_stats(config)
        else:
            if args.platform in ("linkedin", "both"):
                run_linkedin(config, ai_service, dedup, notifier, dry_run=args.dry_run)

            if args.platform in ("naukri", "both"):
                # Add delay between platforms
                if args.platform == "both":
                    delay = random.uniform(30, 60)
                    logger.info(f"Waiting {delay:.0f}s before starting Naukri bot...")
                    if not args.dry_run:
                        time.sleep(delay)

                run_naukri(config, ai_service, dedup, notifier, dry_run=args.dry_run)

            # Send daily summary
            stats = dedup.get_stats()
            notifier.daily_summary(
                total_applied=stats["applied"],
                successful=stats["applied"],
                failed=stats["skipped"],
                avg_ats=0,
            )
    except KeyboardInterrupt:
        logger.info("\n[Ctrl+C] Orchestrator process stopped by user. Exiting.")
        sys.exit(0)

    logger.info("Orchestrator finished")


if __name__ == "__main__":
    main()
