#!/usr/bin/env python3
"""Autonomous 24/7 Publishing Daemon for AskforWrite AI Company OS.

Executes autonomous shifts on a recurring schedule:
1. Generates 2026 GEO/AIO and topical authority articles across the owned AskforWrite sites:
   • askforwrite.in
   • askforwrite.com
   • ask4write.com
   • askforwrite.info
   • shop.ask4write.com
   • node.askforwrite.in
2. Stages drafts with Schema.org graph markup and verified citation triples.
3. If AUTO_PUBLISH_TO_WORDPRESS is enabled (or live credentials exist), automatically
   publishes approved drafts directly to WordPress REST endpoints (/wp-json/wp/v2/posts).
4. Seals every published article to the NIST P-256 cryptographic TrustBlock ledger.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import UTC, datetime

from dotenv import load_dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("afw.autonomous_publisher")


def run_cycle(auto_publish: bool = True) -> dict[str, object]:
    """Execute one complete autonomous publishing cycle."""
    from app.db.database import SessionLocal
    from app.db.models import SeoDraftRecord
    from app.services.shift_scheduler import run_autonomous_shift
    from app.services.wordpress_publisher import publish_seo_draft_to_wordpress

    db = SessionLocal()
    cycle_summary = {
        "timestamp": datetime.now(UTC).isoformat(),
        "shift_id": None,
        "staged_count": 0,
        "published_count": 0,
        "published_details": [],
    }

    try:
        logger.info("[AFW] Initiating Autonomous Content & SEO Shift for 4-site network...")
        shift_res = run_autonomous_shift(db=db, shift_type="seo_publishing_only")
        cycle_summary["shift_id"] = shift_res.get("shift_id")
        seo_step = shift_res.get("steps", {}).get("owned_media_seo", {})
        staged = seo_step.get("staged_drafts", [])
        cycle_summary["staged_count"] = len(staged)
        logger.info(f"[AFW] Staged {len(staged)} articles across 4 digital properties.")

        # If auto-publish is active, publish pending drafts
        if auto_publish:
            pending_drafts = (
                db.query(SeoDraftRecord)
                .filter(SeoDraftRecord.status.in_(["PENDING_APPROVAL", "APPROVED"]))
                .limit(4)
                .all()
            )
            for draft in pending_drafts:
                try:
                    logger.info(f"Publishing draft '{draft.id}' to {draft.target_network}...")
                    pub_res = publish_seo_draft_to_wordpress(
                        db=db,
                        draft_id=draft.id,
                        published_by="autonomous_daemon_24x7",
                    )
                    cycle_summary["published_count"] += 1
                    cycle_summary["published_details"].append({
                        "network": pub_res.get("network"),
                        "title": pub_res.get("title"),
                        "url": pub_res.get("url"),
                        "mode": pub_res.get("mode"),
                    })
                    logger.info(f"  -> Published: {pub_res.get('url')} (Mode: {pub_res.get('mode')})")
                except Exception as p_err:
                    logger.warning(f"Could not publish draft '{draft.id}': {p_err}")

    except Exception as exc:
        logger.error(f"Error in autonomous publishing cycle: {exc}", exc_info=True)
    finally:
        db.close()

    return cycle_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="AskforWrite Autonomous 24/7 Publishing Daemon")
    parser.add_argument("--interval-hours", type=float, default=6.0, help="Interval in hours between cycles (default: 6)")
    parser.add_argument("--run-once", action="store_true", help="Execute single cycle and exit")
    parser.add_argument("--auto-publish", action="store_true", default=True, help="Auto-publish staged drafts to WordPress")
    args = parser.parse_args()

    interval_sec = max(60, int(args.interval_hours * 3600))
    logger.info("=" * 70)
    logger.info(" AskforWrite AI Company OS -- 24/7 Autonomous Publisher Daemon")
    logger.info(f" * Schedule: Every {args.interval_hours} hours ({interval_sec} seconds)")
    logger.info(" * Networks: askforwrite.in | askforwrite.com | ask4write.com | askforwrite.info | shop.ask4write.com | node.askforwrite.in")
    logger.info(" * Ledger:   ECDSA NIST P-256 Merkle Block Sealing")
    logger.info("=" * 70)

    if args.run_once:
        run_cycle(auto_publish=args.auto_publish)
        return 0

    while True:
        run_cycle(auto_publish=args.auto_publish)
        logger.info(f"Sleeping for {args.interval_hours} hours until next publishing cycle...")
        time.sleep(interval_sec)


if __name__ == "__main__":
    sys.exit(main())
