#!/bin/bash
# Deployment script for promoting development to production

set -e

echo "=== X Bridge Deployment Script ==="
echo "Current production version:"
cat /opt/x-bridge/VERSION
echo ""
echo "Development version to deploy:"
cat /opt/x-bridge-dev/VERSION
echo ""
read -p "Continue with deployment? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

# Backup current production
echo "Backing up current production..."
sudo cp -r /opt/x-bridge /opt/x-bridge-backup-$(date +%Y%m%d-%H%M%S)

# Stop services
echo "Stopping services..."
sudo systemctl stop x-bridge@*.service

# Deploy new version
echo "Deploying new version..."
sudo cp /opt/x-bridge-dev/bin/x_bridge.py /opt/x-bridge/bin/x_bridge.py
sudo cp /opt/x-bridge-dev/VERSION /opt/x-bridge/VERSION

# Update version in config if needed
sudo sed -i 's/"version": ".*"/"version": "'$(cat /opt/x-bridge-dev/VERSION | grep version | cut -d'"' -f4)'"/' /opt/x-bridge/VERSION

# Restart services
echo "Restarting services..."
sudo systemctl start x-bridge@*.service

echo "Deployment complete!"
echo "New version deployed: $(cat /opt/x-bridge/VERSION | grep version)"
