#!/bin/bash
# Monitor all X bridge services

WEBHOOK_ALERT_URL="your_alert_webhook"  # Optional alert channel

check_service() {
    local service=$1
    if systemctl is-active --quiet x-bridge@$service.service; then
        echo "✅ $service: running"
        
        # Check last log entry time
        last_log=$(journalctl -u x-bridge@$service.service -n 1 --no-pager -o cat 2>/dev/null | head -1)
        echo "   Last activity: $last_log"
    else
        echo "❌ $service: NOT running"
        
        # Send alert if webhook configured
        if [ -n "$WEBHOOK_ALERT_URL" ]; then
            curl -X POST "$WEBHOOK_ALERT_URL" \
                -H "Content-Type: application/json" \
                -d "{\"content\": \"⚠️ Service x-bridge@$service is down!\"}"
        fi
    fi
}

echo "=== X Bridge Monitor - $(date) ==="
for service in investingcom whale_alert kobeissi deltaone; do
    check_service $service
done

# Check disk space
echo -e "\n=== Disk Usage ==="
df -h /opt/x-bridge

# Check database sizes
echo -e "\n=== Database Sizes ==="
for service in investingcom whale_alert kobeissi deltaone; do
    db="/opt/x-bridge/data/$service/tweets.db"
    if [ -f "$db" ]; then
        size=$(du -h "$db" | cut -f1)
        count=$(sqlite3 "$db" "SELECT COUNT(*) FROM processed_tweets;" 2>/dev/null || echo "0")
        echo "$service: $size ($count tweets tracked)"
    fi
done
