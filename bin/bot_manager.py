#!/usr/bin/env python3
"""
Bot Management System - Complete CLI
Commands: list, add, remove, show, logs, validate, translate
"""

import json
import sys
import os
import argparse
import subprocess
import requests
import feedparser
from pathlib import Path

CONFIG_PATH = '/opt/x-bridge/config/channels.json'
TRANS_CONFIG_PATH = '/opt/x-bridge/config/translations.json'

class BotManager:
    def __init__(self):
        self.config = self._load_config()
        self.trans_config = self._load_trans_config()
    
    def _load_config(self):
        try:
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {
                "webhooks": {},
                "twitter_handles": {},
                "rss_sources": {},
                "settings": {"check_interval_minutes": 5}
            }
    
    def _load_trans_config(self):
        try:
            with open(TRANS_CONFIG_PATH, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {"original_bots": {}, "translations": {}}
    
    def _save_config(self):
        with open(CONFIG_PATH, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def _save_trans_config(self):
        with open(TRANS_CONFIG_PATH, 'w') as f:
            json.dump(self.trans_config, f, indent=2)
    
    def validate_webhook(self, webhook_url):
        """Send a test message to verify webhook"""
        print(f"  Testing webhook: {webhook_url[:50]}...")
        try:
            payload = {"content": "🧪 Webhook validation test - X Bridge Bot Manager"}
            response = requests.post(webhook_url, json=payload, timeout=10)
            if response.status_code in [200, 204]:
                return True, "Webhook OK"
            else:
                return False, f"HTTP {response.status_code}"
        except Exception as e:
            return False, str(e)
    
    def validate_twitter_handle(self, twitter_handle):
        """Check if Twitter handle exists and RSS feed works"""
        rss_url = f"https://nitter.net/{twitter_handle}/rss"
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            response = requests.get(rss_url, headers=headers, timeout=10)
            if response.status_code != 200:
                return False, f"RSS feed returned {response.status_code}"
            feed = feedparser.parse(response.content)
            if not feed.entries:
                return False, "No tweets found in feed"
            return True, f"Found {len(feed.entries)} tweets"
        except Exception as e:
            return False, str(e)
    
    def add_bot_with_validation(self, name, twitter_handle, webhook_url, skip_confirm=False):
        """Add a bot with interactive validation"""
        print(f"\n=== Adding bot: {name} ===")
        
        print("1. Testing webhook...")
        ok, msg = self.validate_webhook(webhook_url)
        if not ok:
            print(f"  ❌ Webhook test failed: {msg}")
            return False
        print(f"  ✅ {msg}")
        
        if not skip_confirm:
            confirm = input("  Did you receive the test message in Discord? (y/n): ").lower()
            if confirm != 'y':
                print("  ❌ Webhook validation cancelled by user")
                return False
        
        print("\n2. Validating Twitter handle...")
        ok, msg = self.validate_twitter_handle(twitter_handle)
        if not ok:
            print(f"  ❌ Twitter validation failed: {msg}")
            return False
        print(f"  ✅ {msg}")
        
        print("\n3. Adding bot to config...")
        return self.add_bot(name, twitter_handle, webhook_url)
    
    def list_bots(self):
        """List all configured bots"""
        if not self.config['webhooks']:
            print("No bots configured")
            return
        
        print("\n" + "=" * 60)
        print(f"{'Bot Name':<20} {'Twitter Handle':<20}")
        print("=" * 60)
        
        for name in self.config['webhooks'].keys():
            handle = self.config['twitter_handles'].get(name, 'Unknown')
            print(f"{name:<20} @{handle:<19}")
        
        print("=" * 60)
        print(f"Total: {len(self.config['webhooks'])} bots")
    
    def add_bot(self, name, twitter_handle, webhook_url):
        """Add a new bot"""
        if name in self.config['webhooks']:
            print(f"❌ Bot '{name}' already exists")
            return False
        
        self.config['webhooks'][name] = webhook_url
        self.config['twitter_handles'][name] = twitter_handle
        self.config['rss_sources'][name] = [f"https://nitter.net/{twitter_handle}/rss"]
        
        self._save_config()
        print(f"✅ Added bot '{name}' (@{twitter_handle})")
        return True
    
    def remove_bot(self, name):
        """Remove a bot"""
        if name not in self.config['webhooks']:
            print(f"❌ Bot '{name}' not found")
            return False
        
        del self.config['webhooks'][name]
        del self.config['twitter_handles'][name]
        del self.config['rss_sources'][name]
        
        self._save_config()
        print(f"✅ Removed bot '{name}'")
        return True
    
    def show_bot(self, name):
        """Show bot details"""
        if name not in self.config['webhooks']:
            print(f"❌ Bot '{name}' not found")
            return
        
        print(f"\n=== Bot: {name} ===")
        print(f"Twitter Handle: @{self.config['twitter_handles'][name]}")
        print(f"RSS Feed: {self.config['rss_sources'][name][0]}")
        
        if name in self.trans_config.get('translations', {}):
            targets = self.trans_config['translations'][name].get('targets', [])
            if targets:
                langs = [t['lang'] for t in targets]
                print(f"Translations: {', '.join(langs)}")
    
    def validate(self):
        """Validate configuration"""
        print("\n=== Config Validation ===")
        errors = []
        
        for name in self.config['webhooks'].keys():
            webhook = self.config['webhooks'][name]
            if not webhook.startswith('https://discord.com/api/webhooks/'):
                errors.append(f"{name}: Invalid webhook URL")
            
            if not self.config['twitter_handles'].get(name):
                errors.append(f"{name}: Missing twitter handle")
        
        if errors:
            print("\n❌ Errors found:")
            for e in errors:
                print(f"  {e}")
        else:
            print("✅ No errors found")
        
        return len(errors) == 0
    
    def translate_enable(self, bot_name, lang, webhook):
        """Enable translation for a bot"""
        if bot_name not in self.config['webhooks']:
            print(f"❌ Bot '{bot_name}' not found")
            return False
        
        if bot_name not in self.trans_config.get('translations', {}):
            self.trans_config.setdefault('translations', {})[bot_name] = {
                "enabled": True,
                "source_lang": "en",
                "targets": []
            }
        
        for target in self.trans_config['translations'][bot_name]['targets']:
            if target['lang'] == lang:
                print(f"⚠️ Translation to {lang} already enabled")
                return False
        
        lang_names = {'de': 'german', 'es': 'spanish', 'fr': 'french', 'nl': 'dutch'}
        self.trans_config['translations'][bot_name]['targets'].append({
            "lang": lang,
            "name": lang_names.get(lang, lang),
            "webhook": webhook
        })
        
        if bot_name not in self.trans_config.get('original_bots', {}):
            self.trans_config.setdefault('original_bots', {})[bot_name] = {
                "enabled": True,
                "twitter_handle": self.config['twitter_handles'][bot_name],
                "webhook": self.config['webhooks'][bot_name]
            }
        
        self._save_trans_config()
        print(f"✅ Enabled {lang} translation for {bot_name}")
        return True
    
    def translate_disable(self, bot_name, lang):
        """Disable translation for a bot"""
        if bot_name not in self.trans_config.get('translations', {}):
            print(f"❌ No translations for {bot_name}")
            return False
        
        targets = self.trans_config['translations'][bot_name]['targets']
        original_count = len(targets)
        self.trans_config['translations'][bot_name]['targets'] = [t for t in targets if t['lang'] != lang]
        
        if len(self.trans_config['translations'][bot_name]['targets']) == original_count:
            print(f"❌ Language {lang} not found")
            return False
        
        self._save_trans_config()
        print(f"✅ Disabled {lang} translation for {bot_name}")
        return True
    
    def translate_list(self):
        """List all translations"""
        if not self.trans_config.get('translations'):
            print("No translations configured")
            return
        
        print("\n=== Enabled Translations ===")
        for bot_name, config in self.trans_config['translations'].items():
            if config.get('enabled') and config.get('targets'):
                langs = [t['lang'] for t in config['targets']]
                print(f"  {bot_name}: {', '.join(langs)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Bot Manager for X Bridge')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    subparsers.add_parser('list', help='List all bots')
    subparsers.add_parser('validate', help='Validate configuration')
    
    add_parser = subparsers.add_parser('add', help='Add a new bot')
    add_parser.add_argument('name', help='Bot name')
    add_parser.add_argument('--twitter', required=True, help='Twitter handle')
    add_parser.add_argument('--webhook', required=True, help='Discord webhook URL')
    add_parser.add_argument('--skip-confirm', action='store_true', help='Skip webhook confirmation')
    
    remove_parser = subparsers.add_parser('remove', help='Remove a bot')
    remove_parser.add_argument('name', help='Bot name')
    
    show_parser = subparsers.add_parser('show', help='Show bot details')
    show_parser.add_argument('name', help='Bot name')
    
    trans_parser = subparsers.add_parser('translate', help='Manage translations')
    trans_subparsers = trans_parser.add_subparsers(dest='trans_command')
    
    enable_parser = trans_subparsers.add_parser('enable', help='Enable translation')
    enable_parser.add_argument('bot', help='Bot name')
    enable_parser.add_argument('--lang', required=True, help='Language code (de)')
    enable_parser.add_argument('--webhook', required=True, help='Webhook for translated posts')
    
    disable_parser = trans_subparsers.add_parser('disable', help='Disable translation')
    disable_parser.add_argument('bot', help='Bot name')
    disable_parser.add_argument('--lang', required=True, help='Language code')
    
    trans_subparsers.add_parser('list', help='List all translations')
    
    args = parser.parse_args()
    manager = BotManager()
    
    if args.command == 'list':
        manager.list_bots()
    elif args.command == 'add':
        manager.add_bot_with_validation(args.name, args.twitter, args.webhook, args.skip_confirm)
    elif args.command == 'remove':
        manager.remove_bot(args.name)
    elif args.command == 'show':
        manager.show_bot(args.name)
    elif args.command == 'validate':
        manager.validate()
    elif args.command == 'translate':
        if args.trans_command == 'enable':
            manager.translate_enable(args.bot, args.lang, args.webhook)
        elif args.trans_command == 'disable':
            manager.translate_disable(args.bot, args.lang)
        elif args.trans_command == 'list':
            manager.translate_list()
        else:
            print("Use: translate enable|disable|list")
    else:
        parser.print_help()
