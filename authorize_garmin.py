import logging
import os
import sys

from dotenv import load_dotenv

try:
    from garminconnect import (
        Garmin,
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
        GarminConnectTooManyRequestsError,
    )
except ImportError:
    Garmin = None
    GarminConnectAuthenticationError = Exception
    GarminConnectConnectionError = Exception
    GarminConnectTooManyRequestsError = Exception


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TOKEN_DIR = ".garmin_session"
TOKEN_FILE_NAME = "garmin_tokens.json"


def prompt_mfa():
    return input("Enter Garmin MFA code: ").strip()


def main():
    load_dotenv()

    if Garmin is None:
        logger.error("garminconnect is not installed. Run: pip install -r requirements.txt")
        sys.exit(1)

    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    if not email or not password:
        logger.error("GARMIN_EMAIL and GARMIN_PASSWORD must be set in .env.")
        sys.exit(1)

    os.makedirs(TOKEN_DIR, exist_ok=True)
    tokenstore = os.path.join(TOKEN_DIR, TOKEN_FILE_NAME)

    try:
        logger.info(f"Logging in to Garmin Connect and saving tokens to {tokenstore}...")
        client = Garmin(email=email, password=password, prompt_mfa=prompt_mfa)
        client.login(tokenstore)
    except GarminConnectAuthenticationError as e:
        logger.error(f"Garmin authentication failed: {e}")
        sys.exit(1)
    except GarminConnectTooManyRequestsError as e:
        logger.error(f"Garmin rate limit reached: {e}")
        sys.exit(1)
    except GarminConnectConnectionError as e:
        logger.error(f"Garmin connection failed: {e}")
        sys.exit(1)

    logger.info("Garmin authorization successful. Restart workout-display to use cached tokens.")


if __name__ == "__main__":
    main()
