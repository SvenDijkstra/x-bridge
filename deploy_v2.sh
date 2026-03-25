#!/bin/bash
# Deployment script for X Bridge v2
# This script safely deploys the new version while keeping v1 as backup

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}X Bridge Deployment Script v2.0${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root (sudo)${NC}"
    exit 1
fi

# Configuration
PROD_DIR="/opt/x-bridge"
DEV_DIR="/opt/x-bridge-dev"
BACKUP_DIR="/opt/x-bridge-backup-$(date +%Y%m%d-%H%M%S)"
VERSION_FILE="/opt/x-bridge/VERSION"

echo -e "${YELLOW}Current version:${NC}"
cat $VERSION_FILE 2>/dev/null || echo "No version file found"

echo ""
echo -e "${YELLOW}This will deploy v2.0 from development to production.${NC}"
echo -e "${YELLOW}A backup will be created at: $BACKUP_DIR${NC}"
echo ""
read -p "Continue? (y/n): " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${RED}Deployment cancelled${NC}"
    exit 1
fi

# Step 1: Stop all production services
echo -e "${BLUE}[1/7] Stopping production services...${NC}"
systemctl stop x-bridge@investingcom.service 2>/dev/null || true
systemctl stop x-bridge@whale_alert.service 2>/dev/null || true
systemctl stop x-bridge@kobeissi.service 2>/dev/null || true
systemctl stop x-bridge@deltaone.service 2>/dev/null || true
systemctl stop x-bridge@realDonaldTrump.service 2>/dev/null || true
systemctl stop x-bridge@FinancialJuice.service 2>/dev/null || true
systemctl stop x-bridge@TruthTrumpPost.service 2>/dev/null || true
systemctl stop x-translator.service 2>/dev/null || true
echo -e "${GREEN}✓ Services stopped${NC}"

# Step 2: Create full backup of production
echo -e "${BLUE}[2/7] Creating backup...${NC}"
mkdir -p $BACKUP_DIR
cp -r $PROD_DIR $BACKUP_DIR/
echo -e "${GREEN}✓ Backup created at $BACKUP_DIR${NC}"

# Step 3: Backup current configs separately
echo -e "${BLUE}[3/7] Backing up configuration...${NC}"
cp $PROD_DIR/config/channels.json $BACKUP_DIR/config/channels.json.bak 2>/dev/null || true
cp $PROD_DIR/config/translations.json $BACKUP_DIR/config/translations.json.bak 2>/dev/null || true
cp $PROD_DIR/data/*.db $BACKUP_DIR/data/ 2>/dev/null || true
echo -e "${GREEN}✓ Configuration backed up${NC}"

# Step 4: Deploy new version
echo -e "${BLUE}[4/7] Deploying v2.0...${NC}"

# Copy the new English bot
cp $DEV_DIR/bin/x_bridge_english.py $PROD_DIR/bin/x_bridge_english.py
chmod +x $PROD_DIR/bin/x_bridge_english.py

# Copy the translation service
cp $DEV_DIR/translator/translator_fixed.py $PROD_DIR/translator/translator.py
chmod +x $PROD_DIR/translator/translator.py

# Copy the bot manager
cp $DEV_DIR/bin/bot_manager.py $PROD_DIR/bin/bot_manager.py
chmod +x $PROD_DIR/bin/bot_manager.py

# Copy health check
cp $DEV_DIR/bin/health_check.py $PROD_DIR/bin/health_check.py
chmod +x $PROD_DIR/bin/health_check.py

# Update configs (preserve webhooks from production)
cp $DEV_DIR/config/channels.json $PROD_DIR/config/channels.json.new
cp $DEV_DIR/config/translations.json $PROD_DIR/config/translations.json.new

# Merge webhooks from old config
python3 << EOF
import json

# Load old config
with open('$PROD_DIR/config/channels.json', 'r') as f:
    old_config = json.load(f)

# Load new config
with open('$PROD_DIR/config/channels.json.new', 'r') as f:
    new_config = json.load(f)

# Preserve webhooks from old config
for bot in old_config.get('webhooks', {}):
    if bot in new_config.get('webhooks', {}):
        new_config['webhooks'][bot] = old_config['webhooks'][bot]

# Save merged config
with open('$PROD_DIR/config/channels.json', 'w') as f:
    json.dump(new_config, f, indent=2)

# Do the same for translations
with open('$PROD_DIR/config/translations.json', 'r') as f:
    old_trans = json.load(f)

with open('$PROD_DIR/config/translations.json.new', 'r') as f:
    new_trans = json.load(f)

# Preserve webhooks
for bot in old_trans.get('original_bots', {}):
    if bot in new_trans.get('original_bots', {}):
        new_trans['original_bots'][bot]['webhook'] = old_trans['original_bots'][bot]['webhook']

for bot in old_trans.get('translations', {}):
    if bot in new_trans.get('translations', {}):
        for i, target in enumerate(old_trans['translations'][bot].get('targets', [])):
            if i < len(new_trans['translations'][bot].get('targets', [])):
                new_trans['translations'][bot]['targets'][i]['webhook'] = target['webhook']

with open('$PROD_DIR/config/translations.json', 'w') as f:
    json.dump(new_trans, f, indent=2)

print("Config merged")
