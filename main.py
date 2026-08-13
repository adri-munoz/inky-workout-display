import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image

# 1. Prepend project root to sys.path before local imports
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from workout_summary.workout_summary import WorkoutDisplay

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def load_config(path="config.json"):
    with open(path, "r") as f:
        return json.load(f)

def save_config(cfg, path="config.json"):
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)

def run_once(args, config):
    display = WorkoutDisplay(config)

    # Merge display config + env credentials into a flat settings dict
    settings = config["plugin_settings"].copy()
    settings.update(config["display"])
    settings["strava_client_id"] = os.getenv("STRAVA_CLIENT_ID")
    settings["strava_client_secret"] = os.getenv("STRAVA_CLIENT_SECRET")
    settings["garmin_email"] = os.getenv("GARMIN_EMAIL")
    settings["garmin_password"] = os.getenv("GARMIN_PASSWORD")
    
    # Track tokens for persistence
    initial_tokens = {
        "access_token": settings.get("access_token"),
        "refresh_token": settings.get("refresh_token"),
        "token_expires_at": settings.get("token_expires_at")
    }
    
    logger.info("Fetching data and generating image...")
    image = display.render(settings)
    
    if not image:
        logger.error("Failed to generate image. Check logs/credentials.")
        return

    # Persist tokens if they were refreshed
    for key in initial_tokens:
        if settings.get(key) != initial_tokens[key]:
            logger.info(f"Token '{key}' updated. Saving to config.json.")
            config["plugin_settings"][key] = settings[key]
            save_config(config)

    # Output handles
    if args.save_image:
        image.save(args.save_image)
        logger.info(f"Image saved to {args.save_image}")

    if not args.no_display:
        try:
            from inky.auto import auto
            inky_display = auto(ask_user=False, verbose=True)
            rgb_image = image.convert('RGB')
            if rgb_image.size != inky_display.resolution:
                rgb_image = rgb_image.resize(inky_display.resolution, Image.LANCZOS)
            inky_display.set_image(rgb_image, saturation=config["display"].get("saturation", 0.5))
            inky_display.show()
            logger.info("Image pushed to Inky Impression display.")
        except ImportError as e:
            logger.error(f"Inky library not found: {e}. Use --no-display for testing.")
        except Exception as e:
            logger.error(f"Failed to show image on display: {e}")

def main():
    parser = argparse.ArgumentParser(description="Standalone Workout Inky Impression display.")
    parser.add_argument("--loop", action="store_true", help="Run in a loop with configured refresh interval.")
    parser.add_argument("--no-display", action="store_true", help="Skip hardware display output.")
    parser.add_argument("--save-image", metavar="PATH", help="Save the generated PIL image to a file.")
    parser.add_argument("--once", action="store_true", help="Run once and exit (default unless --loop).")
    args = parser.parse_args()

    load_dotenv()
    config = load_config()

    if args.loop:
        interval = config.get("refresh_interval_minutes", 15) * 60
        logger.info(f"Starting loop with {interval/60} minute refresh interval.")
        while True:
            try:
                run_once(args, config)
            except Exception as e:
                logger.error(f"Error in cycle: {e}", exc_info=True)
            time.sleep(interval)
    else:
        run_once(args, config)

if __name__ == "__main__":
    main()
