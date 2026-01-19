#!/usr/bin/env python3
"""
Бот за новини от детски градини в Пловдив
Следи dz-priem.plovdiv.bg за новини и уведомява чрез Viber.
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

# Конфигурация на логовете
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Конфигурация от environment променливи
VIBER_BOT_TOKEN = os.getenv('VIBER_BOT_TOKEN')
VIBER_CHAT_ID = os.getenv('VIBER_CHAT_ID')  # ID на групов чат или потребител
NEWS_URL = os.getenv('NEWS_URL', 'https://dz-priem.plovdiv.bg/news')
STATE_FILE = os.getenv('STATE_FILE', '/data/seen_articles.json')
DRY_RUN = os.getenv('DRY_RUN', 'false').lower() == 'true'


@dataclass
class Article:
    """Представя новинарска статия."""
    url: str
    title: str
    date: Optional[str] = None
    summary: Optional[str] = None
    
    @property
    def id(self) -> str:
        """Генерира уникален ID от хеш на URL."""
        return hashlib.sha256(self.url.encode()).hexdigest()[:16]


class StateManager:
    """Управлява състоянието на видените статии."""
    
    def __init__(self, state_file: str):
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set[str] = set()
        self._load()
    
    def _load(self) -> None:
        """Зарежда състоянието от файл."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._seen = set(data.get('seen_ids', []))
                    logger.info(f"Заредени {len(self._seen)} видени статии")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Грешка при зареждане на състоянието: {e}")
                self._seen = set()
    
    def _save(self) -> None:
        """Записва състоянието във файл."""
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump({'seen_ids': list(self._seen), 'updated_at': datetime.now(timezone.utc).isoformat()}, f, indent=2)
        except IOError as e:
            logger.error(f"Грешка при запис на състоянието: {e}")
    
    def is_seen(self, article: Article) -> bool:
        """Проверява дали статията вече е видяна."""
        return article.id in self._seen
    
    def mark_seen(self, article: Article) -> None:
        """Маркира статия като видяна и записва."""
        self._seen.add(article.id)
        self._save()
    
    def get_seen_count(self) -> int:
        """Връща броя видени статии."""
        return len(self._seen)


class NewsScraper:
    """Извлича новини от сайта на общината."""
    
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
        """Извлича и парсва новини от сайта."""
        logger.info(f"Извличане на новини от {self.base_url}")
        
        try:
            response = self.session.get(self.base_url, timeout=30)
            response.raise_for_status()
            response.encoding = 'utf-8'
        except Exception as e:
            logger.error(f"Грешка при извличане на страницата: {e}")
            return []
        
        return self._parse_articles(response.text)
    
    def _parse_articles(self, html: str) -> list[Article]:
        """Парсва статии от HTML съдържание."""
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        
        # Опитваме различни селектори за списъци с новини
        # Селекторите може да се наложи да бъдат коригирани според структурата на сайта
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
                logger.debug(f"Намерени {len(items)} елемента със селектор: {selector}")
                break
        
        if not items:
            # Резервен вариант: търсим всички линкове, които изглеждат като новини
            logger.warning("Не са намерени елементи със стандартни селектори, опитваме извличане на линкове")
            items = soup.find_all('a', href=True)
            items = [a for a in items if self._looks_like_news_link(a)]
        
        for item in items:
            article = self._extract_article(item)
            if article:
                articles.append(article)
        
        logger.info(f"Парснати {len(articles)} статии")
        return articles
    
    def _looks_like_news_link(self, tag) -> bool:
        """Проверява дали линк изглежда като новинарска статия."""
        href = tag.get('href', '')
        text = tag.get_text(strip=True)
        
        # Филтриране на навигационни и социални линкове
        skip_patterns = ['facebook', 'twitter', 'instagram', 'linkedin', 'youtube', 
                        'login', 'register', 'mailto:', 'tel:', '#', 'javascript:']
        
        if any(p in href.lower() for p in skip_patterns):
            return False
        
        # Трябва да има текстово съдържание
        if len(text) < 10:
            return False
            
        # Трябва да е относителен линк или от същия домейн
        if href.startswith('http') and 'plovdiv.bg' not in href:
            return False
            
        return True
    
    def _extract_article(self, item) -> Optional[Article]:
        """Извлича данни за статия от парснат елемент."""
        try:
            # Опитваме да намерим линка
            if item.name == 'a':
                link = item
            else:
                link = item.find('a', href=True)
            
            if not link:
                return None
            
            href = link.get('href', '')
            if not href or href == '#':
                return None
            
            # Нормализиране на URL
            if href.startswith('/'):
                from urllib.parse import urljoin
                url = urljoin(self.base_url, href)
            elif not href.startswith('http'):
                url = f"{self.base_url.rstrip('/')}/{href.lstrip('/')}"
            else:
                url = href
            
            # Вземане на заглавие
            title = link.get_text(strip=True)
            if not title:
                title = link.get('title', '')
            
            if not title or len(title) < 5:
                return None
            
            # Опит за намиране на дата
            date = None
            date_elem = item.find(class_=lambda x: x and ('date' in x.lower() if isinstance(x, str) else any('date' in c.lower() for c in x)))
            if date_elem:
                date = date_elem.get_text(strip=True)
            
            # Опит за намиране на резюме
            summary = None
            for class_hint in ['summary', 'excerpt', 'description', 'text', 'content']:
                summary_elem = item.find(class_=lambda x: x and (class_hint in str(x).lower()))
                if summary_elem:
                    summary = summary_elem.get_text(strip=True)[:200]
                    break
            
            return Article(url=url, title=title, date=date, summary=summary)
            
        except Exception as e:
            logger.debug(f"Грешка при извличане на статия: {e}")
            return None


class ViberBot:
    """Изпраща уведомления чрез Viber Bot API."""
    
    API_URL = 'https://chatapi.viber.com/pa/send_message'
    
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.session = requests.Session()
    
    def send_article(self, article: Article) -> bool:
        """Изпраща уведомление за нова статия."""
        message = self._format_message(article)
        return self._send_message(message, article.url)
    
    def _format_message(self, article: Article) -> str:
        """Форматира статия като съобщение за уведомление."""
        parts = [f"📰 *Ново съобщение*\n\n{article.title}"]
        
        if article.date:
            parts.append(f"\n📅 {article.date}")
        
        if article.summary:
            parts.append(f"\n\n{article.summary}...")
        
        return ''.join(parts)
    
    def _send_message(self, text: str, url: Optional[str] = None) -> bool:
        """Изпраща съобщение чрез Viber API."""
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
                logger.info("Съобщението е изпратено успешно")
                return True
            else:
                logger.error(f"Viber API грешка: {result}")
                return False
                
        except requests.RequestException as e:
            logger.error(f"Грешка при изпращане на Viber съобщение: {e}")
            return False
    
    def send_summary(self, new_count: int, total_count: int) -> bool:
        """Изпраща обобщено уведомление."""
        if new_count == 0:
            logger.info("Няма нови статии за докладване")
            return True
        
        message = f"✅ Проверих за новини от детските градини.\n\n" \
                  f"📊 Нови съобщения: {new_count}\n" \
                  f"📁 Общо следени: {total_count}"
        
        return self._send_message(message)


def main():
    """Главна входна точка."""
    logger.info("Стартиране на бота за новини от детски градини в Пловдив")
    
    # Валидиране на конфигурацията
    if not DRY_RUN and (not VIBER_BOT_TOKEN or not VIBER_CHAT_ID):
        logger.error("VIBER_BOT_TOKEN и VIBER_CHAT_ID са задължителни (освен ако DRY_RUN=true)")
        sys.exit(1)
    
    # Инициализация на компонентите
    state = StateManager(STATE_FILE)
    scraper = NewsScraper(NEWS_URL)
    
    if not DRY_RUN:
        bot = ViberBot(VIBER_BOT_TOKEN, VIBER_CHAT_ID)
    else:
        bot = None
        logger.info("DRY_RUN режим - няма да се изпращат съобщения")
    
    # Извличане и обработка на статии
    articles = scraper.fetch_articles()
    
    if not articles:
        logger.warning("Не са намерени статии")
        return
    
    new_articles = []
    for article in articles:
        if not state.is_seen(article):
            new_articles.append(article)
            logger.info(f"Нова статия: {article.title[:60]}...")
    
    logger.info(f"Намерени {len(new_articles)} нови статии от общо {len(articles)}")
    
    # Изпращане на уведомления за нови статии
    for article in new_articles:
        if bot:
            success = bot.send_article(article)
            if success:
                state.mark_seen(article)
        else:
            # Тестов режим - само маркираме като видяна
            logger.info(f"[ТЕСТ] Би уведомил за: {article.title}")
            logger.info(f"  URL: {article.url}")
            if article.date:
                logger.info(f"  Дата: {article.date}")
            state.mark_seen(article)
    
    # Изпращане на обобщение
    if bot and new_articles:
        bot.send_summary(len(new_articles), state.get_seen_count())
    
    logger.info("Завършено успешно")


if __name__ == '__main__':
    main()
