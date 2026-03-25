#!/usr/bin/env python3
"""
English Bot - Posts to English channel with media support and production-style tracking
"""

import json
import sqlite3
import feedparser
import requests
import time
import logging
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Media extraction functions
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

class EnglishDiscordBridge:
    def __init__(self, account_name: str, config_path: str = '/opt/x-bridge/config/channels.json'):
        self.account_name = account_name
        self.config = self._load_config(config_path)
        self._setup_logging()
        self._init_db()
        
        self.webhook_url = self.config['webhooks'].get(account_name)
        self.twitter_handle = self.config['twitter_handles'].get(account_name)
        self.rss_sources = self.config['rss_sources'].get(account_name, [])
        
        if isinstance(self.rss_sources, str):
            self.rss_sources = [self.rss_sources]
        
        self.logger.info(f"English bot initialized for @{self.twitter_handle}")
    
    def _load_config(self, config_path: str) -> Dict:
        with open(config_path, 'r') as f:
            return json.load(f)
    
    def _setup_logging(self):
        log_dir = Path('/opt/x-bridge/logs/english_bot')
        log_dir.mkdir(parents=True, exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - english-bot - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_dir / 'english_bot.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger('english-bot')
    
    def _init_db(self):
        """Initialize database for tracking posted tweets"""
        db_dir = Path('/opt/x-bridge/data')
        db_dir.mkdir(parents=True, exist_ok=True)
        
        self.db_path = f'/opt/x-bridge/data/english_{self.account_name}.db'
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_tweets (
                tweet_id TEXT PRIMARY KEY,
                posted_at TIMESTAMP,
                tweet_url TEXT,
                content TEXT
            )
        ''')
        conn.commit()
        conn.close()
    
    def _get_last_processed_id(self) -> Optional[str]:
        """Get the last processed tweet ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT tweet_id FROM processed_tweets ORDER BY posted_at DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    
    def _mark_processed(self, tweet_id: str, tweet_url: str, content: str):
        """Mark a tweet as processed"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO processed_tweets (tweet_id, posted_at, tweet_url, content) VALUES (?, ?, ?, ?)",
            (tweet_id, datetime.utcnow().isoformat(), tweet_url, content[:500])
        )
        conn.commit()
        conn.close()
        self.logger.info(f"Marked tweet {tweet_id} as processed")
    
    def fetch_tweets(self) -> List[Dict]:
        """Fetch tweets from RSS feed"""
        rss_url = self.rss_sources[0]
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(rss_url, headers=headers, timeout=15)
            feed = feedparser.parse(response.content)
            
            if not feed.entries:
                return []
            
            tweets = []
            for entry in feed.entries:
                # Clean tweet ID - remove #m and any query parameters
                tweet_id = entry.link.split('/')[-1].replace('#m', '').split('?')[0]
                tweets.append({
                    'id': tweet_id,
                    'title': entry.title,
                    'link': convert_to_twitter_link(entry.link),
                    'published': entry.published,
                    'summary': entry.summary,
                })
            return tweets
        except Exception as e:
            self.logger.error(f"Error fetching tweets: {e}")
            return []
    
    def post_to_discord(self, tweet: Dict) -> bool:
        """Post tweet to Discord with media support"""
        try:
            # Extract media
            media_urls = extract_media(tweet['summary'])
            
            # Clean text
            summary = re.sub(r'<[^>]+>', ' ', tweet['summary'])
            summary = summary.replace('&lt;', '<').replace('&gt;', '>')
            summary = summary.replace('&amp;', '&').replace('&quot;', '"')
            summary = ' '.join(summary.split())[:1900]
            
            # Build embed
            embed = {
                "title": "New Tweet",
                "url": tweet['link'],
                "description": summary[:200],
                "color": 0x1DA1F2,
                "footer": {"text": f"@{self.twitter_handle} • {tweet['published'][:16]}"}
            }
            
            # Add image if available
            if media_urls:
                embed["image"] = {"url": media_urls[0]}
            
            payload = {
                "username": f"📊 {self.twitter_handle}",
                "avatar_url": "https://cdn-icons-png.flaticon.com/512/733/733579.png",
                "content": f"🔵 **@{self.twitter_handle}**\n{tweet['link']}",
                "embeds": [embed]
            }
            
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            return response.status_code in [200, 204]
        except Exception as e:
            self.logger.error(f"Error posting: {e}")
            return False
    
    def run_once(self):
        """Run one cycle - fetches and posts new tweets"""
        self.logger.info("Checking for new tweets...")
        
        tweets = self.fetch_tweets()
        if not tweets:
            self.logger.info("No tweets fetched")
            return
        
        last_processed = self._get_last_processed_id()
        self.logger.info(f"Last processed ID: {last_processed}")
        self.logger.info(f"Latest RSS ID: {tweets[0]['id']}")
        
        # Process tweets in reverse order (oldest first)
        new_tweets = []
        for tweet in reversed(tweets):
            if last_processed and tweet['id'] == last_processed:
                break
            new_tweets.append(tweet)
        
        if not new_tweets:
            self.logger.info("No new tweets to process")
            return
        
        self.logger.info(f"Found {len(new_tweets)} new tweets")
        
        for tweet in new_tweets:
            self.logger.info(f"Posting tweet: {tweet['id']}")
            if self.post_to_discord(tweet):
                self._mark_processed(tweet['id'], tweet['link'], tweet['summary'])
                self.logger.info(f"✅ Posted: {tweet['id']}")
                time.sleep(2)
            else:
                self.logger.error(f"Failed to post tweet {tweet['id']}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    
    bot = EnglishDiscordBridge('investingcom')
    if args.once:
        bot.run_once()
    else:
        while True:
            bot.run_once()
            time.sleep(300)
