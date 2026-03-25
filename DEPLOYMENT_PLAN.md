# X Bridge v2 Deployment Plan

## Current State
- **Production (v1)**: Running at `/opt/x-bridge/` with original bots
- **Development (v2)**: Tested at `/opt/x-bridge-dev/` with all features working

## Backup Strategy
1. Full backup of `/opt/x-bridge/` before any changes
2. Backup of all databases and configs
3. Git tag of v1 for easy rollback

## Deployment Steps (Manual, Safe Approach)

### Phase 1: Prepare Backup
```bash
# Create full backup
sudo cp -r /opt/x-bridge /opt/x-bridge-backup-v1-$(date +%Y%m%d)

# Backup databases
sudo mkdir -p /opt/x-bridge-backup-data
sudo cp /opt/x-bridge/data/*.db /opt/x-bridge-backup-data/

# Backup configs
sudo cp /opt/x-bridge/config/channels.json /opt/x-bridge-backup-config/
sudo cp /opt/x-bridge/config/translations.json /opt/x-bridge-backup-config/
