#!/usr/bin/env python3
"""
Translation Service - Posts translations of tweets to multiple language channels
Runs independently from the main bot
"""

import json
import sqlite3
import feedparser
import requests
import time
import logging
import sys
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import threading
from concurrent.futures import ThreadPoolExecutor

class TranslationService:
    def __init__(self, config_path: str = '/opt/x-bridge/config/translations.json'):
        self.config = self._load_config(config_path)
        self._setup_logging()
        self._init_databases()
        
        # Translation service clients
        self.translators = {}
        self._init_translators()
        
        # Cache for translations (avoid duplicate API calls)
        self.cache = TranslationCache()
        
        self.logger.info("Translation Service initialized")
    
    def _load_config(self, config_path: str) -> Dict:
        with open(config_path, 'r') as f:
            return json.load(f)
    
    def _setup_logging(self):
        log_dir = Path('/opt/x-bridge/logs/translator')
        log_dir.mkdir(parents=True, exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - translator - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_dir / 'translator.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger('translator')
    
    def _init_databases(self):
        """Create translation tracking database"""
        self.db_path = '/opt/x-bridge/data/translations.db'
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS translated_tweets (
                tweet_id TEXT PRIMARY KEY,
                original_text TEXT,
                translations TEXT,  # JSON of {lang: translated_text}
                posted_at TIMESTAMP,
                languages TEXT      # Comma-separated list of languages posted
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def _init_translators(self):
        """Initialize translation service clients"""
        service_type = self.config.get('translation_service', {}).get('type', 'libretranslate')
        
        if service_type == 'libretranslate':
            from services.libretranslate import LibreTranslateClient
            endpoint = self.config.get('translation_service', {}).get('endpoint', 'http://localhost:5000')
            self.translator = LibreTranslateClient(endpoint)
        elif service_type == 'deepl':
            from services.deepl import DeepLClient
            api_key = self.config.get('translation_service', {}).get('api_key')
            self.translator = DeepLClient(api_key)
        else:
            from services.mock import MockTranslator
            self.translator = MockTranslator()
    
    def translate_text(self, text: str, source_lang: str, target_lang: str) -> Optional[str]:
        """Translate text with caching"""
        # Create cache key
        cache_key = hashlib.md5(f"{text}_{source_lang}_{target_lang}".encode()).hexdigest()
        
        # Check cache
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        # Call translation API
        try:
            translated = self.translator.translate(text, source_lang, target_lang)
            if translated:
                self.cache.set(cache_key, translated, ttl=3600)
            return translated
        except Exception as e:
            self.logger.error(f"Translation failed: {e}")
            return None
    
    def get_translated_webhooks(self, bot_name: str, tweet_id: str) -> List[Dict]:
        """Determine which translations need to be posted"""
        config = self.config.get('translations', {}).get(bot_name)
        if not config or not config.get('enabled', True):
            return []
        
        # Check database to see if already posted
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT languages FROM translated_tweets WHERE tweet_id = ?", (tweet_id,))
        result = cursor.fetchone()
        conn.close()
        
        posted_langs = set()
        if result:
            posted_langs = set(result[0].split(','))
        
        # Determine which languages need translation
        targets = []
        for target in config.get('targets', []):
            lang = target['lang']
            if lang not in posted_langs:
                targets.append(target)
        
        return targets
    
    def mark_as_posted(self, tweet_id: str, languages: List[str]):
        """Mark tweet as translated for specific languages"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get existing
        cursor.execute("SELECT languages FROM translated_tweets WHERE tweet_id = ?", (tweet_id,))
        result = cursor.fetchone()
        
        if result:
            existing_langs = set(result[0].split(','))
            existing_langs.update(languages)
            langs_str = ','.join(existing_langs)
            
            cursor.execute(
                "UPDATE translated_tweets SET languages = ? WHERE tweet_id = ?",
                (langs_str, tweet_id)
            )
        else:
            # This shouldn't happen if we store original first
            pass
        
        conn.commit()
        conn.close()
    
    def store_original(self, tweet_id: str, original_text: str):
        """Store original tweet in database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR IGNORE INTO translated_tweets (tweet_id, original_text, posted_at, languages)
            VALUES (?, ?, ?, ?)
        ''', (tweet_id, original_text, datetime.utcnow().isoformat(), ''))
        
        conn.commit()
        conn.close()
    
    def post_translation(self, webhook_url: str, original_link: str, original_text: str, 
                        translated_text: str, lang: str, source_bot: str):
        """Post translated tweet to Discord"""
        payload = {
            "username": f"🌐 {source_bot} ({lang.upper()})",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/2990/2990502.png",
            "content": f"**Translated ({lang.upper()})**\n{original_link}",
            "embeds": [{
                "title": f"📝 {lang.upper()} Translation",
                "url": original_link,
                "description": translated_text[:1900],
                "color": 0x00FF00,
                "footer": {
                    "text": f"Translated from {source_bot} • Original: {original_text[:100]}..."
                }
            }]
        }
        
        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            return response.status_code in [200, 204]
        except Exception as e:
            self.logger.error(f"Failed to post translation: {e}")
            return False
    
    def process_tweet(self, bot_name: str, tweet: Dict):
        """Process a single tweet for all required translations"""
        self.logger.info(f"Processing translations for {bot_name}: {tweet['id']}")
        
        # Store original if not already stored
        self.store_original(tweet['id'], tweet['summary'])
        
        # Get which translations are needed
        targets = self.get_translated_webhooks(bot_name, tweet['id'])
        if not targets:
            self.logger.info(f"No new translations needed for {tweet['id']}")
            return
        
        self.logger.info(f"Translating into {len(targets)} languages: {[t['lang'] for t in targets]}")
        
        # Translate in parallel
        translations = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {}
            for target in targets:
                future = executor.submit(
                    self.translate_text,
                    tweet['summary'],
                    self.config['translations'][bot_name]['source_lang'],
                    target['lang']
                )
                futures[future] = target
            
            for future in futures:
                target = futures[future]
                translated = future.result()
                if translated:
                    translations[target['lang']] = translated
                    # Post to Discord
                    success = self.post_translation(
                        target['webhook'],
                        tweet['link'],
                        tweet['summary'],
                        translated,
                        target['lang'],
                        bot_name
                    )
                    if success:
                        self.logger.info(f"Posted {target['lang']} translation for {tweet['id']}")
                    time.sleep(1)  # Rate limit
        
        # Mark as posted for languages that succeeded
        posted_langs = list(translations.keys())
        if posted_langs:
            self.mark_as_posted(tweet['id'], posted_langs)
    
    def run_once(self):
        """Check for new tweets and process translations"""
        self.logger.info("Checking for new tweets to translate...")
        
        # For each bot configured for translation
        for bot_name, config in self.config.get('translations', {}).items():
            if not config.get('enabled', True):
                continue
            
            # Get bot's RSS feed
            twitter_handle = self.config['original_bots'].get(bot_name, {}).get('twitter_handle')
            if not twitter_handle:
                self.logger.warning(f"No twitter handle for {bot_name}")
                continue
            
            # Fetch RSS
            rss_url = f"https://nitter.net/{twitter_handle}/rss"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            
            try:
                response = requests.get(rss_url, headers=headers, timeout=15)
                feed = feedparser.parse(response.content)
                
                if not feed.entries:
                    continue
                
                # Check each tweet
                for entry in feed.entries[:10]:  # Check last 10
                    tweet_id = entry.link.split('/')[-1].replace('#m', '').split('?')[0]
                    
                    # Check if already processed for translations
                    conn = sqlite3.connect(self.db_path)
                    cursor = conn.cursor()
                    cursor.execute("SELECT languages FROM translated_tweets WHERE tweet_id = ?", (tweet_id,))
                    result = cursor.fetchone()
                    conn.close()
                    
                    if result:
                        # Already processed, check if all languages are done
                        posted = set(result[0].split(',')) if result[0] else set()
                        target_langs = set([t['lang'] for t in config.get('targets', [])])
                        if posted.issuperset(target_langs):
                            continue
                    
                    # Process this tweet
                    tweet = {
                        'id': tweet_id,
                        'link': entry.link,
                        'summary': entry.summary,
                        'title': entry.title
                    }
                    self.process_tweet(bot_name, tweet)
                    
            except Exception as e:
                self.logger.error(f"Error processing {bot_name}: {e}")
    
    def run_daemon(self):
        """Run as a daemon"""
        import schedule
        
        interval = self.config.get('settings', {}).get('check_interval_minutes', 5)
        schedule.every(interval).minutes.do(self.run_once)
        
        self.logger.info(f"Translation service started, checking every {interval} minutes")
        
        # Run once immediately
        self.run_once()
        
        while True:
            schedule.run_pending()
            time.sleep(60)

class TranslationCache:
    """Simple cache for translations"""
    def __init__(self):
        self.cache = {}
    
    def get(self, key):
        entry = self.cache.get(key)
        if entry and entry['expires'] > time.time():
            return entry['value']
        return None
    
    def set(self, key, value, ttl=3600):
        self.cache[key] = {
            'value': value,
            'expires': time.time() + ttl
        }

if __name__ == "__main__":
    service = TranslationService()
    if len(sys.argv) > 1 and sys.argv[1] == '--once':
        service.run_once()
    else:
        service.run_daemon()
