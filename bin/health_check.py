#!/usr/bin/env python3
"""Health check for X Bridge services"""

import json
import sqlite3
import sys
import os
import requests
from datetime import datetime

def check_config():
    """Check if config files exist and are valid"""
    config_files = [
        "/opt/x-bridge-dev/config/channels.json",
        "/opt/x-bridge-dev/config/translations.json"
    ]
    for f in config_files:
        if not os.path.exists(f):
            return False, f"Missing config: {f}"
        try:
            with open(f, 'r') as fp:
                json.load(fp)
        except Exception as e:
            return False, f"Invalid config {f}: {e}"
    return True, "Config OK"

def check_database():
    """Check database integrity"""
    db_path = "/opt/x-bridge-dev/data/translations.db"
    if not os.path.exists(db_path):
        return False, "Database not found"
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM translated_tweets")
        count = cursor.fetchone()[0]
        conn.close()
        return True, f"Database OK ({count} translations)"
    except Exception as e:
        return False, f"Database error: {e}"

def check_translation_api():
    """Check if Lingva API is responding"""
    try:
        response = requests.get("https://lingva.ml/api/v1/en/de/Hello", timeout=10)
        if response.status_code == 200:
            return True, "Translation API OK"
        return False, f"API returned {response.status_code}"
    except Exception as e:
        return False, f"API error: {e}"

def main():
    """Run all health checks"""
    print(f"=== Health Check: {datetime.now()} ===")
    print()
    
    checks = [
        ("Config", check_config),
        ("Database", check_database),
        ("Translation API", check_translation_api),
    ]
    
    all_ok = True
    for name, check_func in checks:
        ok, msg = check_func()
        status = "✅" if ok else "❌"
        print(f"{status} {name}: {msg}")
        if not ok:
            all_ok = False
    
    sys.exit(0 if all_ok else 1)

if __name__ == "__main__":
    main()
