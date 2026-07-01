"""
Signal HN Monitor
-----------------
Monitors Hacker News top stories and uses Signal to learn what you care about.

First run: escalates to Slack for each story and waits for your decision.
After a few runs: Signal auto-filters based on your decisions. No more noise.

The escalate() call itself blocks until the Slack decision flow is finalized:
one-time action chosen, rule approved, rule discarded, or auto-resolved.
When the resolution propagator fires, related escalations unblock automatically.

Setup:
    pip install httpx signal-sdk apscheduler

Run once:
    python hn_monitor.py --once

Run on schedule (every 30 min):
    python hn_monitor.py --schedule
"""

import asyncio
import httpx
import argparse
import json
import os
from datetime import datetime
from signal_sdk import Signal

# ─── Config ───────────────────────────────────────────────────────────────────

SIGNAL_API_KEY = os.getenv("SIGNAL_API_KEY", "YOUR_SIGNAL_API_KEY")
SIGNAL_BASE_URL = os.getenv("SIGNAL_BASE_URL", "https://YOUR_SIGNAL_BASE_URL")

STORIES_TO_CHECK = 15
MIN_SCORE = 50
HN_API = "https://hacker-news.firebaseio.com/v0"

# ─── Story Categories ──────────────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "ai_ml":        ["gpt", "llm", "claude", "openai", "anthropic", "gemini", "mistral",
                     "machine learning", "neural", "diffusion", "transformer", "agent",
                     "artificial intelligence", " ai ", "deep learning", "embeddings"],
    "startups":     ["startup", "yc ", "y combinator", "seed", "series a", "founder",
                     "vc ", "venture", "acquisition", "ipo", "valuation"],
    "programming":  ["python", "javascript", "typescript", "rust", "golang", "compiler",
                     "framework", "library", "open source", "github", "debugging",
                     "architecture", "database", "api", "backend", "frontend"],
    "security":     ["hack", "vulnerability", "exploit", "breach", "malware", "ransomware",
                     "phishing", "cve", "security", "privacy", "encryption"],
    "science":      ["research", "study", "paper", "scientists", "discovery", "physics",
                     "biology", "chemistry", "space", "nasa", "cern"],
    "business":     ["revenue", "profit", "layoffs", "hiring", "remote", "saas",
                     "enterprise", "market", "economy", "inflation"],
    "crypto":       ["bitcoin", "ethereum", "crypto", "blockchain", "defi", "nft", "web3"],
    "other":        []
}


def classify_story(title: str, url: str) -> str:
    title_lower = title.lower()
    url_lower = (url or "").lower()
    combined = title_lower + " " + url_lower

    for category, keywords in CATEGORY_KEYWORDS.items():
        if category == "other":
            continue
        if any(kw in combined for kw in keywords):
            return category

    return "other"


def score_tier(score: int) -> str:
    if score >= 500:
        return "viral"
    elif score >= 200:
        return "hot"
    elif score >= 100:
        return "trending"
    else:
        return "normal"


def comment_tier(comments: int) -> str:
    if comments >= 200:
        return "high"
    elif comments >= 50:
        return "medium"
    else:
        return "low"


def extract_domain(url: str) -> str:
    if not url:
        return "news.ycombinator.com"
    try:
        parts = url.split("/")
        domain = parts[2] if len(parts) > 2 else url
        domain = domain.replace("www.", "")
        return domain
    except Exception:
        return "unknown"


# ─── HN API ───────────────────────────────────────────────────────────────────

async def fetch_top_story_ids(client: httpx.AsyncClient) -> list[int]:
    response = await client.get(f"{HN_API}/topstories.json")
    response.raise_for_status()
    return response.json()[:STORIES_TO_CHECK * 3]


async def fetch_story(client: httpx.AsyncClient, story_id: int) -> dict | None:
    try:
        response = await client.get(f"{HN_API}/item/{story_id}.json")
        response.raise_for_status()
        data = response.json()
        if not data or data.get("type") != "story" or not data.get("title"):
            return None
        return data
    except Exception:
        return None


async def fetch_top_stories(count: int = STORIES_TO_CHECK) -> list[dict]:
    async with httpx.AsyncClient(timeout=30) as client:
        story_ids = await fetch_top_story_ids(client)
        tasks = [fetch_story(client, sid) for sid in story_ids]
        stories = await asyncio.gather(*tasks)
        valid = [s for s in stories if s and s.get("score", 0) >= MIN_SCORE]
        valid.sort(key=lambda s: s.get("score", 0), reverse=True)
        return valid[:count]


# ─── Seen Stories ─────────────────────────────────────────────────────────────

SEEN_FILE = "/tmp/signal_hn_seen.json"


def load_seen() -> set[int]:
    try:
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen: set[int]):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


# ─── Main Agent Logic ──────────────────────────────────────────────────────────

async def process_story(signal: Signal, story: dict, seen: set[int]) -> str:
    """
    Process a single HN story through Signal.

    signal.escalate() blocks until the Slack flow is finalized OR the
    resolution propagator auto-resolves it because a matching rule was just created.

    Returns: 'notified' | 'skipped' | 'escalated' | 'auto_resolved' | 'seen'
    """
    story_id = story["id"]

    if story_id in seen:
        return "seen"

    title    = story.get("title", "")
    url      = story.get("url", f"https://news.ycombinator.com/item?id={story_id}")
    score    = story.get("score", 0)
    comments = story.get("descendants", 0)
    author   = story.get("by", "unknown")

    category = classify_story(title, url)
    metadata = {
        "story_id":     story_id,
        "category":     category,
        "score_tier":   score_tier(score),
        "score":        score,
        "comment_tier": comment_tier(comments),
        "comments":     comments,
        "domain":       extract_domain(url),
        "author":       author,
        "has_url":      bool(story.get("url"))
    }

    print(f"\n  [{category.upper()}] {title[:70]}")
    print(f"  Score: {score} ({score_tier(score)}) | "
          f"Comments: {comments} | {extract_domain(url)}")

    # Step 1: Check against existing rules first
    check = await signal.check(
        action="notify_user",
        agent_id="hn-monitor",
        context=metadata
    )

    if check.rule_id is not None:
        if check.result == "proceed":
            print(f"  ✅ AUTO-NOTIFY (rule matched)")
            print(f"  📬 {title}")
            print(f"  🔗 {url}")
            seen.add(story_id)
            return "notified"

        elif check.result == "block":
            print(f"  ⏭️  AUTO-SKIP (rule matched)")
            seen.add(story_id)
            return "skipped"

    # Step 2: No rule matched — escalate.
    # This call blocks here until either:
    #   a) You choose one-time in Slack
    #   b) You approve or discard the proposed rule
    #   c) The resolution propagator auto-resolves it because you approved
    #      a rule for a different story with matching conditions
    if check.result == "escalate":
        print(f"  ⚠️  Conflicting rules matched — sent to Slack, waiting for response...")
        print(f"  Reason: {check.reasoning}")
    else:
        print(f"  ❓ No rule found — sent to Slack, waiting for response...")

    result = await signal.escalate(
        context=(
            f"New Hacker News story:\n\n"
            f"Title: {title}\n"
            f"URL: {url}\n"
            f"Score: {score} | Comments: {comments}\n"
            f"Category: {category} | Domain: {extract_domain(url)}"
        ),
        question="Should I notify you about this story?",
        agent_id="hn-monitor",
        metadata=metadata,
        timeout_seconds=3600
    )

    # Was this auto-resolved by the propagator?
    if getattr(result, "auto_resolved", False):
        print(f"  ⚡ Auto-resolved: {result.decision.upper()}")
        if result.decision in ("approve", "proceed"):
            print(f"  📬 {title}")
            print(f"  🔗 {url}")
        seen.add(story_id)
        return "auto_resolved"

    # Human responded manually
    print(f"  → Decision: {result.decision.upper()}")
    if result.decision in ("approve", "yes", "notify"):
        print(f"  📬 {title}")
        print(f"  🔗 {url}")
    if result.rule_id:
        print(f"  → Rule created — similar stories will resolve automatically")

    seen.add(story_id)
    return "escalated"


async def run_once():
    print(f"\n{'='*60}")
    print(f"🤖 Signal HN Monitor")
    print(f"{'='*60}")
    print(f"Fetching top {STORIES_TO_CHECK} HN stories (min score: {MIN_SCORE})...")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\nHow this works:")
    print(f"  - Stories with a matching rule resolve instantly")
    print(f"  - Stories without a rule send a Slack card and wait")
    print(f"  - The next story is not checked until the current decision returns")
    print(f"  - Approve a rule → later matching stories resolve automatically\n")

    signal = Signal(
        api_key=SIGNAL_API_KEY,
        base_url=SIGNAL_BASE_URL
    )

    seen = load_seen()
    stories = await fetch_top_stories()

    print(f"Found {len(stories)} stories to evaluate\n")

    stats = {"notified": 0, "skipped": 0, "escalated": 0, "auto_resolved": 0, "seen": 0}

    # Process Signal decisions sequentially. Fetching HN data above can be
    # concurrent, but escalation decisions should not flood Slack.
    for story in stories:
        try:
            result = await process_story(signal, story, seen)
        except Exception as exc:
            print(f"  Error: {exc}")
            continue

        stats[result] += 1
        save_seen(seen)

    print(f"\n{'='*60}")
    print(f"RUN COMPLETE")
    print(f"{'='*60}")
    print(f"✅ Auto-notified:    {stats['notified']}")
    print(f"⏭️  Auto-skipped:     {stats['skipped']}")
    print(f"⚡ Auto-resolved:    {stats['auto_resolved']}")
    print(f"❓ Human decided:    {stats['escalated']}")
    print(f"👁️  Already seen:     {stats['seen']}")
    print(f"\nRun again to see more rules apply automatically.")


async def run_scheduled():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    print("🤖 Signal HN Monitor — Scheduled Mode")
    print("Running every 30 minutes. Press Ctrl+C to stop.\n")

    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_once, 'interval', minutes=30)
    scheduler.start()

    await run_once()

    try:
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        print("\nStopped.")
        scheduler.shutdown()


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Signal HN Monitor")
    parser.add_argument("--once",      action="store_true", help="Run once and exit")
    parser.add_argument("--schedule",  action="store_true", help="Run every 30 minutes")
    parser.add_argument("--stories",   type=int, default=STORIES_TO_CHECK,
                        help=f"Stories per run (default: {STORIES_TO_CHECK})")
    parser.add_argument("--min-score", type=int, default=MIN_SCORE,
                        help=f"Minimum score (default: {MIN_SCORE})")
    args = parser.parse_args()

    STORIES_TO_CHECK = args.stories
    MIN_SCORE = args.min_score

    if args.schedule:
        asyncio.run(run_scheduled())
    else:
        asyncio.run(run_once())
