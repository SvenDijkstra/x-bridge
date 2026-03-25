#!/usr/bin/env python3

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
from typing import Dict, List, Optional, Tuple

class XDiscordBridge:
    def __init__(self, account_name: str, config_path: str = '/opt/x-bridge/config/channels.json'):
        self.account_name = account_name
        self.config = self._load_config(config_path)
        
        self._setup_logging()
        
        self.db_path = f'/opt/x-bridge/data/{account_name}/tweets.db'
        self._init_db()
        
        self.webhook_url = self.config['webhooks'].get(account_name)
        self.twitter_handle = self.config['twitter_handles'].get(account_name)
        self.rss_sources = self.config['rss_sources'].get(account_name, [])
        
        if isinstance(self.rss_sources, str):
            self.rss_sources = [self.rss_sources]
        
        self.logger.info(f"Initialized bridge for @{self.twitter_handle}")
    
    def _load_config(self, config_path: str) -> Dict:
        with open(config_path, 'r') as f:
            return json.load(f)
    
    def _setup_logging(self):
        log_dir = Path(f'/opt/x-bridge/logs/{self.account_name}')
        log_dir.mkdir(parents=True, exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_dir / 'bridge.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(f'x-bridge.{self.account_name}')
    
    def _init_db(self):
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
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT tweet_id FROM processed_tweets ORDER BY posted_at DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    
    def _mark_processed(self, tweet_id: str, tweet_url: str, content: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO processed_tweets (tweet_id, posted_at, tweet_url, content) VALUES (?, ?, ?, ?)",
            (tweet_id, datetime.utcnow().isoformat(), tweet_url, content[:500])
        )
        conn.commit()
        conn.close()
        self.logger.info(f"Marked tweet {tweet_id} as processed")
    
    def fetch_tweets_from_source(self, rss_url: str) -> Tuple[List[Dict], bool]:
        try:
            self.logger.info(f"Trying RSS feed: {rss_url}")
            
            # Add browser headers to avoid blocking
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/rss+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            # Use requests to fetch with headers, then parse
            response = requests.get(rss_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            # Parse the response content
            feed = feedparser.parse(response.content)
            
            if not feed.entries:
                self.logger.warning(f"No entries found in feed")
                return [], False
            
            tweets = []
            for entry in feed.entries:
                # Extract clean tweet ID
                tweet_id = entry.link.split('/')[-1].replace('#m', '').split('?')[0]
                
                tweets.append({
                    'id': tweet_id,
                    'title': entry.title,
                    'link': entry.link,
                    'published': entry.published,
                    'summary': entry.summary,
                })
            
            self.logger.info(f"Fetched {len(tweets)} tweets")
            return tweets, True
            
        except Exception as e:
            self.logger.error(f"Error fetching from {rss_url}: {e}")
            return [], False
    
    def fetch_tweets(self) -> List[Dict]:
        for rss_url in self.rss_sources:
            tweets, success = self.fetch_tweets_from_source(rss_url)
            if success and tweets:
                return tweets
        return []
    
    def post_to_discord(self, tweet: Dict) -> bool:
        try:
            summary = re.sub(r'<[^>]+>', ' ', tweet['summary'])
            summary = summary.replace('&lt;', '<').replace('&gt;', '>')
            summary = summary.replace('&amp;', '&').replace('&quot;', '"')
            summary = ' '.join(summary.split())[:1900]
            
            payload = {
                "username": f"📊 {self.twitter_handle}",
                "content": f"🔵 **@{self.twitter_handle}**\n{tweet['link']}",
                "embeds": [{
                    "title": "New Tweet",
                    "url": tweet['link'],
                    "description": summary[:200],
                    "color": 0x1DA1F2,
                    "footer": {"text": f"@{self.twitter_handle}"}
                }]
            }
            
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            return response.status_code in [200, 204]
            
        except Exception as e:
            self.logger.error(f"Error posting: {e}")
            return False
    
    def run_once(self):
        self.logger.info("Starting update cycle")
        
        tweets = self.fetch_tweets()
        if not tweets:
            self.logger.info("No tweets fetched")
            return
        
        last_processed = self._get_last_processed_id()
        
        new_tweets = []
        for tweet in tweets:
            if last_processed and tweet['id'] == last_processed:
                break
            new_tweets.append(tweet)
        
        if not new_tweets:
            self.logger.info("No new tweets to process")
            return
        
        self.logger.info(f"Found {len(new_tweets)} new tweets")
        
        for tweet in reversed(new_tweets[:5]):  # Max 5 per cycle
            if self.post_to_discord(tweet):
                self._mark_processed(tweet['id'], tweet['link'], tweet['summary'])
                time.sleep(2)
            else:
                break
    
    def run_once_and_exit(self):
        self.logger.info("Running single update cycle")
        self.run_once()
        self.logger.info("Update cycle complete, exiting")
    
    def run_daemon(self):
        import schedule
        interval = self.config['settings']['check_interval_minutes']
        schedule.every(interval).minutes.do(self.run_once)
        self.logger.info(f"Starting daemon, checking every {interval} minutes")
        self.run_once()
        while True:
            schedule.run_pending()
            time.sleep(60)

if __name__ == "__main__":
    if len(sys.argv) not in [2, 3]:
        print("Usage: x_bridge.py <account_name> [--once]")
        sys.exit(1)
    
    account = sys.argv[1]
    run_once = len(sys.argv) == 3 and sys.argv[2] == '--once'
    
    bridge = XDiscordBridge(account)
    if run_once:
        bridge.run_once_and_exit()
    else:
        bridge.run_daemon()

    def __init__(self, account_name: str, config_path: str = '/opt/x-bridge/config/channels.json', dry_run: bool = False):
        # ... existing init code ...
        self.dry_run = dry_run
        if dry_run:
            self.logger.warning("DRY RUN MODE - Will not post to Discord")
    
    def post_to_discord(self, tweet: Dict) -> bool:
        if self.dry_run:
            self.logger.info(f"DRY RUN: Would post tweet {tweet['id']}")
            return True
        # ... rest of existing post code ...
