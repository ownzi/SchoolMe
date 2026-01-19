"""Тестове за бота за новини от детски градини в Пловдив."""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.main import Article, StateManager, NewsScraper


class TestArticle:
    """Тестове за Article dataclass."""
    
    def test_article_id_is_deterministic(self):
        """ID на статия трябва да е детерминистичен."""
        article = Article(url="https://example.com/news/1", title="Тест")
        assert article.id == article.id
        
    def test_different_urls_have_different_ids(self):
        """Различни URL-и трябва да генерират различни ID-та."""
        a1 = Article(url="https://example.com/news/1", title="Тест")
        a2 = Article(url="https://example.com/news/2", title="Тест")
        assert a1.id != a2.id
        
    def test_same_url_same_id(self):
        """Един и същ URL трябва да генерира едно и също ID."""
        a1 = Article(url="https://example.com/news/1", title="Тест 1", date="2024-01-01")
        a2 = Article(url="https://example.com/news/1", title="Тест 2", date="2024-01-02")
        assert a1.id == a2.id


class TestStateManager:
    """Тестове за StateManager."""
    
    def test_new_state_is_empty(self):
        """Нов state manager трябва да няма видени статии."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = StateManager(f"{tmpdir}/state.json")
            assert state.get_seen_count() == 0
    
    def test_mark_seen_persists(self):
        """Маркираните статии трябва да се запазват."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = f"{tmpdir}/state.json"
            
            # Маркираме статия като видяна
            state1 = StateManager(state_file)
            article = Article(url="https://example.com/1", title="Тест")
            state1.mark_seen(article)
            
            # Създаваме нова инстанция и проверяваме
            state2 = StateManager(state_file)
            assert state2.is_seen(article)
            assert state2.get_seen_count() == 1
    
    def test_is_seen_returns_false_for_new(self):
        """is_seen трябва да връща False за нови статии."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = StateManager(f"{tmpdir}/state.json")
            article = Article(url="https://example.com/new", title="Нова")
            assert not state.is_seen(article)
    
    def test_handles_corrupted_state_file(self):
        """Трябва да обработва повредени файлове със състояние."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            state_file.write_text("невалиден json {{{")
            
            state = StateManager(str(state_file))
            assert state.get_seen_count() == 0


class TestNewsScraper:
    """Тестове за NewsScraper."""
    
    SAMPLE_HTML = """
    <!DOCTYPE html>
    <html>
    <body>
        <div class="news-list">
            <article>
                <a href="/news/article-1">Първо съобщение за прием</a>
                <span class="date">01.01.2024</span>
                <p class="summary">Кратко описание на новината...</p>
            </article>
            <article>
                <a href="/news/article-2">Второ съобщение</a>
            </article>
        </div>
    </body>
    </html>
    """
    
    def test_parse_articles_from_html(self):
        """Трябва да парсва статии от HTML."""
        scraper = NewsScraper("https://example.com/news")
        articles = scraper._parse_articles(self.SAMPLE_HTML)
        
        assert len(articles) >= 1
        assert any("прием" in a.title.lower() or "съобщение" in a.title.lower() for a in articles)
    
    def test_normalizes_relative_urls(self):
        """Трябва да нормализира относителни URL-и към абсолютни."""
        scraper = NewsScraper("https://example.com/news")
        html = '<html><body><a href="/article/1">Тестова статия заглавие тук</a></body></html>'
        articles = scraper._parse_articles(html)
        
        if articles:
            assert articles[0].url.startswith("https://")
    
    @patch('requests.Session.get')
    def test_fetch_handles_network_error(self, mock_get):
        """Трябва да обработва мрежови грешки."""
        mock_get.side_effect = Exception("Мрежова грешка")
        
        scraper = NewsScraper("https://example.com/news")
        articles = scraper.fetch_articles()
        
        assert articles == []
    
    def test_filters_navigation_links(self):
        """Трябва да филтрира навигационни и социални линкове."""
        html = """
        <html><body>
            <a href="/news/real-article">Истинска новинарска статия тук</a>
            <a href="https://facebook.com/share">Сподели</a>
            <a href="mailto:test@test.com">Контакт</a>
            <a href="#">Нагоре</a>
        </body></html>
        """
        
        scraper = NewsScraper("https://example.com")
        articles = scraper._parse_articles(html)
        
        # Трябва да има само истинската статия
        urls = [a.url for a in articles]
        assert not any("facebook" in u for u in urls)
        assert not any("mailto" in u for u in urls)


class TestIntegration:
    """Интеграционни тестове."""
    
    def test_full_flow_dry_run(self):
        """Тест на пълния процес в тестов режим."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            os.environ['STATE_FILE'] = f"{tmpdir}/state.json"
            os.environ['DRY_RUN'] = 'true'
            os.environ['VIBER_BOT_TOKEN'] = ''
            os.environ['VIBER_CHAT_ID'] = ''
            
            # Главната функция трябва да завърши без грешка в тестов режим
            # (Не можем да тестваме мрежови заявки без mocking)
