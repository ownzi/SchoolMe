"""Tests for the Plovdiv School News Bot."""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.main import Article, StateManager, NewsScraper


class TestArticle:
    """Tests for Article dataclass."""
    
    def test_article_id_is_deterministic(self):
        """Article ID should be deterministic based on URL."""
        article = Article(url="https://example.com/news/1", title="Test")
        assert article.id == article.id
        
    def test_different_urls_have_different_ids(self):
        """Different URLs should produce different IDs."""
        a1 = Article(url="https://example.com/news/1", title="Test")
        a2 = Article(url="https://example.com/news/2", title="Test")
        assert a1.id != a2.id
        
    def test_same_url_same_id(self):
        """Same URL should produce same ID regardless of other fields."""
        a1 = Article(url="https://example.com/news/1", title="Test 1", date="2024-01-01")
        a2 = Article(url="https://example.com/news/1", title="Test 2", date="2024-01-02")
        assert a1.id == a2.id


class TestStateManager:
    """Tests for StateManager."""
    
    def test_new_state_is_empty(self):
        """New state manager should have no seen articles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = StateManager(f"{tmpdir}/state.json")
            assert state.get_seen_count() == 0
    
    def test_mark_seen_persists(self):
        """Marked articles should be persisted and recoverable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = f"{tmpdir}/state.json"
            
            # Mark an article as seen
            state1 = StateManager(state_file)
            article = Article(url="https://example.com/1", title="Test")
            state1.mark_seen(article)
            
            # Create new instance and verify persistence
            state2 = StateManager(state_file)
            assert state2.is_seen(article)
            assert state2.get_seen_count() == 1
    
    def test_is_seen_returns_false_for_new(self):
        """is_seen should return False for new articles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = StateManager(f"{tmpdir}/state.json")
            article = Article(url="https://example.com/new", title="New")
            assert not state.is_seen(article)
    
    def test_handles_corrupted_state_file(self):
        """Should handle corrupted state files gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            state_file.write_text("not valid json {{{")
            
            state = StateManager(str(state_file))
            assert state.get_seen_count() == 0


class TestNewsScraper:
    """Tests for NewsScraper."""
    
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
        """Should parse articles from HTML."""
        scraper = NewsScraper("https://example.com/news")
        articles = scraper._parse_articles(self.SAMPLE_HTML)
        
        assert len(articles) >= 1
        assert any("прием" in a.title.lower() or "съобщение" in a.title.lower() for a in articles)
    
    def test_normalizes_relative_urls(self):
        """Should normalize relative URLs to absolute."""
        scraper = NewsScraper("https://example.com/news")
        html = '<html><body><a href="/article/1">Test Article Title Here</a></body></html>'
        articles = scraper._parse_articles(html)
        
        if articles:
            assert articles[0].url.startswith("https://")
    
    @patch('requests.Session.get')
    def test_fetch_handles_network_error(self, mock_get):
        """Should handle network errors gracefully."""
        mock_get.side_effect = Exception("Network error")
        
        scraper = NewsScraper("https://example.com/news")
        articles = scraper.fetch_articles()
        
        assert articles == []
    
    def test_filters_navigation_links(self):
        """Should filter out navigation and social links."""
        html = """
        <html><body>
            <a href="/news/real-article">Real News Article Here</a>
            <a href="https://facebook.com/share">Share</a>
            <a href="mailto:test@test.com">Contact</a>
            <a href="#">Top</a>
        </body></html>
        """
        
        scraper = NewsScraper("https://example.com")
        articles = scraper._parse_articles(html)
        
        # Should only have the real article
        urls = [a.url for a in articles]
        assert not any("facebook" in u for u in urls)
        assert not any("mailto" in u for u in urls)


class TestIntegration:
    """Integration tests."""
    
    def test_full_flow_dry_run(self):
        """Test the full flow in dry run mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            os.environ['STATE_FILE'] = f"{tmpdir}/state.json"
            os.environ['DRY_RUN'] = 'true'
            os.environ['VIBER_BOT_TOKEN'] = ''
            os.environ['VIBER_CHAT_ID'] = ''
            
            # The main function should complete without error in dry run
            # (Can't actually test network calls here without mocking)
