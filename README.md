# Workout Inky Impression Display

Displays your workout activity summary from Strava or Garmin Connect on a [Pimoroni Inky Impression 7.3"](https://shop.pimoroni.com/products/inky-impression-7-3) e-ink display connected to a Raspberry Pi.

<img src="https://github.com/user-attachments/assets/6a50f0a9-7465-42c8-90d7-6bf7dcfb3c85" />

## What it shows

- Weekly activity summary (runs, cycling rides, swims, strength, racketsports and yoga)
- Activity icons with duration, frequency and distance (where applicable)
- Rolling weekly view of daily activities

## Requirements

- Raspberry Pi (any model with GPIO header)
- Pimoroni Inky Impression 7.3" (2025 Edition, SKU: PIM773)
- Strava account with API access or a Garmin Connect account

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/adri-munoz/inky-workout-display
cd inky-workout-display
```

### 2. Run the setup script

```bash
chmod +x setup.sh
./setup.sh
```

This will:
- Enable I2C and SPI interfaces
- Add the required `dtoverlay=spi0-0cs` to `/boot/firmware/config.txt`
- Install system dependencies (`libopenblas0`)
- Create a Python virtual environment and install dependencies
- Create a `.env` template for Strava and Garmin credentials

**A reboot is required after setup.**

### 3. Choose a data source

Edit `config.json` and set `plugin_settings.use_garmin`:

```json
"use_garmin": true
```

Use `true` for Garmin Connect or `false` for Strava. Restart the service after changing this value.

### 4. Garmin setup

Add Garmin credentials to `.env`:

```
GARMIN_EMAIL=your_email@example.com
GARMIN_PASSWORD=your_garmin_password_here
```

Run once to log in and cache Garmin session tokens:

```bash
source .venv/bin/activate
python3 authorize_garmin.py
sudo systemctl restart workout-display
```

If Garmin asks for MFA, enter the code in the terminal. Tokens are saved under `.garmin_session/`, which is ignored by git. The service can reuse those cached tokens on future restarts.

### 5. Strava setup

1. Go to [strava.com/settings/api](https://www.strava.com/settings/api)
2. Create an application — set the callback domain to `localhost`
3. Copy your **Client ID** and **Client Secret** into `.env`:

```
STRAVA_CLIENT_ID=your_client_id_here
STRAVA_CLIENT_SECRET=your_client_secret_here
```

Run once to complete the OAuth flow and save your tokens to `config.json`:

```bash
source .venv/bin/activate
python3 authorize.py
sudo systemctl start workout-display
```

If running into issues when authorizing, see the troubleshooting section below.

The service starts automatically on boot and refreshes on the interval set in `config.json`.

## Usage

```bash
# Check service status
sudo systemctl status workout-display

# View live logs
sudo journalctl -u workout-display -f

# Restart after config changes
sudo systemctl restart workout-display

# Stop the service
sudo systemctl stop workout-display
```

## Configuration

Edit `config.json` to change display behaviour:

```json
{
  "display": {
    "resolution": [800, 480],
    "orientation": "horizontal",
    "saturation": 0.5
  },
  "plugin_settings": {
    "use_garmin": true,
    "display_mode": "combined",
    "time_mode": "rolling",
    "days_back": 7,
    "time_type": "moving_time",
    "garmin_token_dir": ".garmin_session",
    "garmin_token_file_name": "garmin_tokens.json"
  },
  "refresh_interval_minutes": 15
}
```

| Setting | Options | Description |
|---|---|---|
| `use_garmin` | `true`, `false` | `true` fetches from Garmin Connect; `false` fetches from Strava |
| `display_mode` | `combined`, `calendar`, `stats` | Layout style |
| `time_mode` | `rolling`, `current_week` | Rolling 7 days vs current week |
| `days_back` | integer | Number of days to look back (rolling mode) |
| `time_type` | `moving_time`, `elapsed_time` | Which time to display |
| `garmin_token_dir` | path | Garmin session token cache directory |
| `garmin_token_file_name` | filename | Garmin session token cache file |
| `saturation` | 0.0 – 1.0 | Colour saturation of the e-ink display |

## Troubleshooting

### `RuntimeError: No EEPROM detected!`

I2C or SPI is not enabled. Run:

```bash
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0
sudo reboot
```

### `Chip Select: (line 8, GPIO8) currently claimed by spi0 CS0`

The SPI chip-select overlay is missing. Add it and reboot:

```bash
echo "dtoverlay=spi0-0cs" | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

### `libopenblas.so.0: cannot open shared object file` / `libopenjp2.so.7: cannot open shared object file`

NumPy or Pillow is missing a system library:

```bash
sudo apt-get install -y libopenblas0 libopenjp2-7
```

### `No module named 'dotenv'` or other missing modules

Make sure you have the virtual environment active:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### `ERR_CONNECTION_REFUSED` when authorizing from your laptop

`authorize.py` runs a local HTTP server on the Pi (port 8080) and waits for Strava's OAuth redirect to `localhost:8080/callback`. Because the redirect lands in **your laptop's** browser, nothing is listening on your laptop's port 8080 — hence the refused connection.

Fix: open an SSH tunnel from your laptop **before** running the script on the Pi.

**Terminal 1 — on your laptop (keep this running):**

```bash
ssh -L 8080:localhost:8080 pi@raspberrypi.local -N
```

**Terminal 2 — on the Pi:**

```bash
cd ~/workout-display
source .venv/bin/activate
python3 authorize.py
```

Strava will redirect your browser to `localhost:8080/callback`, which the tunnel forwards to the Pi. You'll see "Success!" in the browser and tokens saved to `config.json`. Once done, Ctrl-C the tunnel in Terminal 1.

### Icons not appearing on display

Icon files may not have been cloned. Verify:

```bash
ls workout_summary/images/
```

You should see `Bike.png`, `Run.png`, `Strength.png`, `Swim.png`, `Tennis.png`, `Padel.png`, `Yoga.png`.

## Credits

- **[Pimoroni Inky](https://github.com/pimoroni/inky)** — Python library for driving the Inky Impression display
- **[DM Sans](https://fonts.google.com/specimen/DM Sans)** by Colophon Foundry — licensed under the [SIL Open Font License 1.1](https://scripts.sil.org/OFL)
