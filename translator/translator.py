#!/usr/bin/env python3
"""
Translation Service - Working with Media Support
"""

import json
import sqlite3
import feedparser
import requests
import time
import logging
import sys
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

class LingvaTranslator:
    def __init__(self):
        self.timeout = 15
        self.base_url = "https://lingva.ml/api/v1"
        self.last_request = 0
        self.min_interval = 1
    
    def translate(self, text: str, source_lang: str, target_lang: str) -> Optional[str]:
        try:
            elapsed = time.time() - self.last_request
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            
            clean_text = re.sub(r'<[^>]+>', ' ', text)
            clean_text = re.sub(r'&[a-z]+;', ' ', clean_text)
            clean_text = re.sub(r'https?://\S+', '[LINK]', clean_text)
            clean_text = ' '.join(clean_text.split())
            
            if len(clean_text) > 500:
                clean_text = clean_text[:497] + "..."
            
            import urllib.parse
            encoded_text = urllib.parse.quote(clean_text)
            url = f"{self.base_url}/{source_lang}/{target_lang}/{encoded_text}"
            
            response = requests.get(url, timeout=self.timeout)
            self.last_request = time.time()
            
            if response.status_code == 200:
                data = response.json()
                return data.get('translation')
            return None
        except Exception as e:
            return None

def convert_to_twitter_link(nitter_link):
    """Convert nitter.net link to x.com link"""
    match = re.search(r'nitter\.net/([^/]+)/status/(\d+)', nitter_link)
    if match:
        handle = match.group(1)
        tweet_id = match.group(2)
        return f"https://x.com/{handle}/status/{tweet_id}"
    return nitter_link

def convert_to_twitter_url(nitter_url):
    """Convert nitter.net image URL to direct Twitter media URL"""
    if 'nitter.net/pic/media%2F' in nitter_url:
        media_id = nitter_url.split('media%2F')[-1]
        return f"https://pbs.twimg.com/media/{media_id}"
    return nitter_url

def extract_media(html_content):
    """Extract image URLs from HTML content and convert to Twitter URLs"""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        images = []
        for img in soup.find_all("img"):
            src = img.get("src")
            if src:
                if 'nitter.net/pic/' in src:
                    src = convert_to_twitter_url(src)
                if src.startswith("http"):
                    images.append(src)
        return images[:4]
    except:
        return []

class TranslationService:
    def __init__(self, config_path: str = '/opt/x-bridge/config/translations.json', dry_run: bool = False):
        self.config_path = config_path
        self.dry_run = dry_run
        self.config = self._load_config()
        self._setup_logging()
        self._init_databases()
        
        self.translator = LingvaTranslator()
        test_result = self.translator.translate("Hello World", "en", "de")
        if test_result:
            self.logger.info(f"✓ Lingva API working")
        else:
            self.logger.error("❌ Translation API failed")
            sys.exit(1)
        
        self.cache = {}
        self.logger.info(f"Translation Service initialized (dry_run={dry_run})")
    
    def _load_config(self) -> Dict:
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Error loading config: {e}")
            return {}
    
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
        db_dir = Path('/opt/x-bridge/data')
        db_dir.mkdir(parents=True, exist_ok=True)
        
        self.db_path = '/opt/x-bridge/data/translations.db'
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS translated_tweets (
                tweet_id TEXT PRIMARY KEY,
                original_text TEXT,
                translated_text TEXT,
                posted_at TIMESTAMP,
                languages TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def translate_text(self, text: str, source_lang: str, target_lang: str) -> Optional[str]:
        clean_text = re.sub(r'<[^>]+>', ' ', text)[:200]
        cache_key = hashlib.md5(f"{clean_text}_{source_lang}_{target_lang}".encode()).hexdigest()
        
        if cache_key in self.cache:
            cached = self.cache[cache_key]
            if cached['expires'] > time.time():
                return cached['value']
        
        translated = self.translator.translate(text, source_lang, target_lang)
        if translated:
            self.cache[cache_key] = {'value': translated, 'expires': time.time() + 86400}
        return translated
    
    def get_translations_needed(self, bot_name: str, tweet_id: str) -> List[Dict]:
        config = self.config.get('translations', {}).get(bot_name)
        if not config or not config.get('enabled', True):
            return []
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT languages FROM translated_tweets WHERE tweet_id = ?", (tweet_id,))
        result = cursor.fetchone()
        conn.close()
        
        posted_langs = set(result[0].split(',')) if result and result[0] else set()
        
        targets = []
        for target in config.get('targets', []):
            if target['lang'] not in posted_langs:
                targets.append(target)
        
        return targets
    
    def mark_as_posted(self, tweet_id: str, languages: List[str], translated_text: str = ""):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT languages FROM translated_tweets WHERE tweet_id = ?", (tweet_id,))
        result = cursor.fetchone()
        
        if result and result[0]:
            existing = set(result[0].split(','))
            existing.update(languages)
            langs_str = ','.join(existing)
            cursor.execute("UPDATE translated_tweets SET languages = ? WHERE tweet_id = ?", (langs_str, tweet_id))
        else:
            langs_str = ','.join(languages)
            cursor.execute("INSERT INTO translated_tweets (tweet_id, languages, posted_at, translated_text) VALUES (?, ?, ?, ?)",
                          (tweet_id, langs_str, datetime.utcnow().isoformat(), translated_text[:500]))
        
        conn.commit()
        conn.close()
        self.logger.info(f"✓ Marked {tweet_id} for langs: {languages}")
    
    def post_translation(self, webhook_url: str, original_link: str, translated_text: str, lang: str, source_bot: str, media_urls=None):
        """Post to Discord - respects dry_run flag"""
        if self.dry_run:
            self.logger.info(f"📤 [DRY RUN] Would post to webhook for {lang}")
            self.logger.info(f"   Translation: {translated_text[:100]}...")
            return True
        
        # Build embed with media if available
        embed = {
            "title": f"📝 {lang.upper()} Translation",
            "url": original_link,
            "description": translated_text[:1900],
            "color": 0x00FF00,
            "footer": {"text": f"Translated from @{source_bot} via Lingva API"}
        }
        
        # Add first image if media exists
        if media_urls and len(media_urls) > 0:
            embed["image"] = {"url": media_urls[0]}
        
        payload = {
            "username": f"🌐 {source_bot} ({lang.upper()})",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/2990/2990502.png",
            "content": f"**🇩🇪 German Translation**\n{original_link}",
            "embeds": [embed]
        }
        
        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            if response.status_code in [200, 204]:
                self.logger.info(f"✅ Posted {lang} translation for {original_link}")
                return True
            else:
                self.logger.error(f"❌ Failed to post: {response.status_code}")
                return False
        except Exception as e:
            self.logger.error(f"❌ Error posting: {e}")
            return False
    
    def process_tweet(self, bot_name: str, tweet: Dict):
        self.logger.info(f"Processing {bot_name}: {tweet['id']}")
        
        # Extract media from tweet
        media_urls = extract_media(tweet['summary'])
        if media_urls:
            self.logger.info(f"  Found {len(media_urls)} media URLs")
        
        targets = self.get_translations_needed(bot_name, tweet['id'])
        if not targets:
            self.logger.info("No new translations needed")
            return
        
        self.logger.info(f"Translating into {len(targets)} languages")
        
        source_lang = self.config['translations'][bot_name]['source_lang']
        posted_langs = []
        
        for target in targets:
            self.logger.info(f"  → Translating to {target['lang']}...")
            translated = self.translate_text(tweet['summary'][:500], source_lang, target['lang'])
            if translated:
                success = self.post_translation(target['webhook'], tweet['link'], translated, target['lang'], bot_name, media_urls)
                if success:
                    posted_langs.append(target['lang'])
                    self.logger.info(f"  ✓ Translation: {translated[:80]}...")
                time.sleep(1)
            else:
                self.logger.warning(f"  ✗ Failed to translate to {target['lang']}")
        
        if posted_langs:
            self.mark_as_posted(tweet['id'], posted_langs)
    
    def run_once(self):
        self.logger.info("=" * 50)
        self.logger.info("Checking for new tweets...")
        
        for bot_name, config in self.config.get('translations', {}).items():
            if not config.get('enabled', True):
                continue
            
            original_bot = self.config.get('original_bots', {}).get(bot_name)
            if not original_bot:
                continue
            
            twitter_handle = original_bot.get('twitter_handle')
            if not twitter_handle:
                continue
            
            rss_url = f"https://nitter.net/{twitter_handle}/rss"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            
            try:
                response = requests.get(rss_url, headers=headers, timeout=15)
                feed = feedparser.parse(response.content)
                
                if not feed.entries:
                    continue
                
                self.logger.info(f"Found {len(feed.entries)} tweets for {bot_name}")
                
                for entry in feed.entries[:3]:
                    tweet_id = entry.link.split('/')[-1].replace('#m', '').split('?')[0]
                    
                    # Convert to real Twitter link
                    real_link = convert_to_twitter_link(entry.link)
                    
                    conn = sqlite3.connect(self.db_path)
                    cursor = conn.cursor()
                    cursor.execute("SELECT tweet_id FROM translated_tweets WHERE tweet_id = ?", (tweet_id,))
                    exists = cursor.fetchone()
                    conn.close()
                    
                    if exists:
                        continue
                    
                    tweet = {
                        'id': tweet_id,
                        'link': real_link,
                        'summary': entry.summary,
                        'title': entry.title
                    }
                    self.process_tweet(bot_name, tweet)
                    
            except Exception as e:
                self.logger.error(f"Error processing {bot_name}: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='Run once')
    parser.add_argument('--dry-run', action="store_true", default=False, help="Dry run - no Discord posts")
    args = parser.parse_args()
    
    service = TranslationService(dry_run=args.dry_run)
    if args.once:
        service.run_once()
    else:
        print("Use --once flag for testing")
        service.run_once()
