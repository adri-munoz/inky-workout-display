#!/bin/bash
# Setup script for Workout Inky Impression display

set -e

echo "Setting up Workout Inky Impression display..."

# Enable I2C and SPI interfaces
echo "Enabling I2C and SPI..."
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0

# Disable SPI chip-select to avoid pin conflict with Inky
CONFIG_FILE="/boot/firmware/config.txt"
if ! grep -q "dtoverlay=spi0-0cs" "$CONFIG_FILE"; then
    echo "Adding dtoverlay=spi0-0cs to $CONFIG_FILE..."
    echo "dtoverlay=spi0-0cs" | sudo tee -a "$CONFIG_FILE"
else
    echo "dtoverlay=spi0-0cs already present in $CONFIG_FILE"
fi

# Install system dependencies
echo "Installing system dependencies..."
sudo apt-get install -y libopenblas0 libopenjp2-7 libfreetype6

# Set up Python virtual environment
echo "Creating Python virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Set up .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env template..."
    cat > .env << 'EOF'
STRAVA_CLIENT_ID=your_client_id_here
STRAVA_CLIENT_SECRET=your_client_secret_here
GARMIN_EMAIL=your_email@example.com
GARMIN_PASSWORD=your_garmin_password_here
EOF
    echo ".env file created. Fill in credentials for your selected data source."
fi

# Set up systemd service
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_USER="$(whoami)"

echo "Setting up systemd service..."
sudo tee /etc/systemd/system/workout-display.service > /dev/null << EOF
[Unit]
Description=Workout Inky Impression Display
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${SCRIPT_DIR}/.venv/bin/python3 ${SCRIPT_DIR}/main.py --loop
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable workout-display

echo ""
echo "Setup complete! A reboot is required for I2C/SPI changes to take effect."
echo ""
echo "After rebooting:"
echo "  1. Set plugin_settings.use_garmin in config.json for Garmin (true) or Strava (false)"
echo "  2. Fill in credentials for your selected data source in .env"
echo "  3. Authorize once:"
echo "     Garmin: source .venv/bin/activate && python3 authorize_garmin.py"
echo "     Strava: source .venv/bin/activate && python3 authorize.py"
echo "  4. Start the service: sudo systemctl start workout-display"
echo "  5. Check logs: sudo journalctl -u workout-display -f"
echo ""
read -p "Reboot now? [y/N] " answer
if [[ "$answer" =~ ^[Yy]$ ]]; then
    sudo reboot
fi
