#!/usr/bin/env python3
"""
Plovdiv School News Bot
Scrapes dz-priem.plovdiv.bg for news and notifies via Viber.
"""

import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Configuration from environment
VIBER_BOT_TOKEN = os.getenv('VIBER_BOT_TOKEN')
VIBER_CHAT_ID = os.getenv('VIBER_CHAT_ID')  # Group chat ID or user ID
NEWS_URL = os.getenv('NEWS_URL', 'https://dz-priem.plovdiv.bg/news')
STATE_FILE = os.getenv('STATE_FILE', '/data/seen_articles.json')
DRY_RUN = os.getenv('DRY_RUN', 'false').lower() == 'true'


@dataclass
class Article:
    """Represents a news article."""
    url: str
    title: str
    date: Optional[str] = None
    summary: Optional[str] = None
    
    @property
    def id(self) -> str:
        """Generate unique ID from URL hash."""
        return hashlib.sha256(self.url.encode()).hexdigest()[:16]


class StateManager:
    """Manages persistent state of seen articles."""
    
    def __init__(self, state_file: str):
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set[str] = set()
        self._load()
    
    def _load(self) -> None:
        """Load state from file."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._seen = set(data.get('seen_ids', []))
                    logger.info(f"Loaded {len(self._seen)} seen article IDs")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load state: {e}")
                self._seen = set()
    
    def _save(self) -> None:
        """Save state to file."""
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump({'seen_ids': list(self._seen), 'updated_at': datetime.now(timezone.utc).isoformat()}, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save state: {e}")
    
    def is_seen(self, article: Article) -> bool:
        """Check if article was already seen."""
        return article.id in self._seen
    
    def mark_seen(self, article: Article) -> None:
        """Mark article as seen and persist."""
        self._seen.add(article.id)
        self._save()
    
    def get_seen_count(self) -> int:
        """Return count of seen articles."""
        return len(self._seen)


class NewsScraper:
    """Scrapes news from the municipality website."""
    
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'bg,en;q=0.9',
    }
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
    
    def fetch_articles(self) -> list[Article]:
        """Fetch and parse news articles from the website."""
        logger.info(f"Fetching news from {self.base_url}")
        
        try:
            response = self.session.get(self.base_url, timeout=30)
            response.raise_for_status()
            response.encoding = 'utf-8'
        except Exception as e:
            logger.error(f"Failed to fetch news page: {e}")
            return []
        
        return self._parse_articles(response.text)
    
    def _parse_articles(self, html: str) -> list[Article]:
        """Parse articles from HTML content."""
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        
        # Try multiple common selectors for news listings
        # The actual selectors will need adjustment based on the real site structure
        selectors = [
            'article',
            '.news-item',
            '.news-article', 
            '.news-list-item',
            '.list-item',
            'div[class*="news"]',
            '.content-list article',
            '.news a',
            'ul.news li',
            '.panel-body a',
        ]
        
        items = []
        for selector in selectors:
            items = soup.select(selector)
            if items:
                logger.debug(f"Found {len(items)} items with selector: {selector}")
                break
        
        if not items:
            # Fallback: find all links that look like news articles
            logger.warning("No items found with standard selectors, trying link extraction")
            items = soup.find_all('a', href=True)
            items = [a for a in items if self._looks_like_news_link(a)]
        
        for item in items:
            article = self._extract_article(item)
            if article:
                articles.append(article)
        
        logger.info(f"Parsed {len(articles)} articles")
        return articles
    
    def _looks_like_news_link(self, tag) -> bool:
        """Check if a link looks like a news article."""
        href = tag.get('href', '')
        text = tag.get_text(strip=True)
        
        # Filter out navigation, social links, etc.
        skip_patterns = ['facebook', 'twitter', 'instagram', 'linkedin', 'youtube', 
                        'login', 'register', 'mailto:', 'tel:', '#', 'javascript:']
        
        if any(p in href.lower() for p in skip_patterns):
            return False
        
        # Must have some text content
        if len(text) < 10:
            return False
            
        # Should be a relative or same-domain link
        if href.startswith('http') and 'plovdiv.bg' not in href:
            return False
            
        return True
    
    def _extract_article(self, item) -> Optional[Article]:
        """Extract article data from a parsed item."""
        try:
            # Try to find the link
            if item.name == 'a':
                link = item
            else:
                link = item.find('a', href=True)
            
            if not link:
                return None
            
            href = link.get('href', '')
            if not href or href == '#':
                return None
            
            # Normalize URL
            if href.startswith('/'):
                # Extract base domain from self.base_url
                from urllib.parse import urljoin
                url = urljoin(self.base_url, href)
            elif not href.startswith('http'):
                url = f"{self.base_url.rstrip('/')}/{href.lstrip('/')}"
            else:
                url = href
            
            # Get title
            title = link.get_text(strip=True)
            if not title:
                title = link.get('title', '')
            
            if not title or len(title) < 5:
                return None
            
            # Try to find date
            date = None
            date_elem = item.find(class_=lambda x: x and ('date' in x.lower() if isinstance(x, str) else any('date' in c.lower() for c in x)))
            if date_elem:
                date = date_elem.get_text(strip=True)
            
            # Try to find summary/excerpt
            summary = None
            for class_hint in ['summary', 'excerpt', 'description', 'text', 'content']:
                summary_elem = item.find(class_=lambda x: x and (class_hint in str(x).lower()))
                if summary_elem:
                    summary = summary_elem.get_text(strip=True)[:200]
                    break
            
            return Article(url=url, title=title, date=date, summary=summary)
            
        except Exception as e:
            logger.debug(f"Failed to extract article: {e}")
            return None


class ViberBot:
    """Sends notifications via Viber Bot API."""
    
    API_URL = 'https://chatapi.viber.com/pa/send_message'
    
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.session = requests.Session()
    
    def send_article(self, article: Article) -> bool:
        """Send a notification about a new article."""
        message = self._format_message(article)
        return self._send_message(message, article.url)
    
    def _format_message(self, article: Article) -> str:
        """Format article as a notification message."""
        parts = [f"📰 *Ново съобщение*\n\n{article.title}"]
        
        if article.date:
            parts.append(f"\n📅 {article.date}")
        
        if article.summary:
            parts.append(f"\n\n{article.summary}...")
        
        return ''.join(parts)
    
    def _send_message(self, text: str, url: Optional[str] = None) -> bool:
        """Send a message via Viber API."""
        payload = {
            'receiver': self.chat_id,
            'type': 'url' if url else 'text',
            'text': text,
        }
        
        if url:
            payload['media'] = url
        
        headers = {
            'X-Viber-Auth-Token': self.token,
            'Content-Type': 'application/json'
        }
        
        try:
            response = self.session.post(
                self.API_URL,
                json=payload,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            result = response.json()
            
            if result.get('status') == 0:
                logger.info(f"Message sent successfully")
                return True
            else:
                logger.error(f"Viber API error: {result}")
                return False
                
        except requests.RequestException as e:
            logger.error(f"Failed to send Viber message: {e}")
            return False
    
    def send_summary(self, new_count: int, total_count: int) -> bool:
        """Send a summary notification."""
        if new_count == 0:
            logger.info("No new articles to report")
            return True
        
        message = f"✅ Проверих за новини от детските градини.\n\n" \
                  f"📊 Нови съобщения: {new_count}\n" \
                  f"📁 Общо следени: {total_count}"
        
        return self._send_message(message)


def main():
    """Main entry point."""
    logger.info("Starting Plovdiv School News Bot")
    
    # Validate configuration
    if not DRY_RUN and (not VIBER_BOT_TOKEN or not VIBER_CHAT_ID):
        logger.error("VIBER_BOT_TOKEN and VIBER_CHAT_ID are required (unless DRY_RUN=true)")
        sys.exit(1)
    
    # Initialize components
    state = StateManager(STATE_FILE)
    scraper = NewsScraper(NEWS_URL)
    
    if not DRY_RUN:
        bot = ViberBot(VIBER_BOT_TOKEN, VIBER_CHAT_ID)
    else:
        bot = None
        logger.info("DRY_RUN mode - no messages will be sent")
    
    # Fetch and process articles
    articles = scraper.fetch_articles()
    
    if not articles:
        logger.warning("No articles found")
        return
    
    new_articles = []
    for article in articles:
        if not state.is_seen(article):
            new_articles.append(article)
            logger.info(f"New article: {article.title[:60]}...")
    
    logger.info(f"Found {len(new_articles)} new articles out of {len(articles)} total")
    
    # Send notifications for new articles
    for article in new_articles:
        if bot:
            success = bot.send_article(article)
            if success:
                state.mark_seen(article)
        else:
            # Dry run - just mark as seen
            logger.info(f"[DRY RUN] Would notify: {article.title}")
            logger.info(f"  URL: {article.url}")
            if article.date:
                logger.info(f"  Date: {article.date}")
            state.mark_seen(article)
    
    # Send summary
    if bot and new_articles:
        bot.send_summary(len(new_articles), state.get_seen_count())
    
    logger.info("Completed successfully")


if __name__ == '__main__':
    main()
