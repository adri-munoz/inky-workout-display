import os
import sys
import json
import webbrowser
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
import requests

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PORT = 8080
REDIRECT_URI = f"http://localhost:{PORT}/callback"
AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"

# Target config path
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        query_components = parse_qs(urlparse(self.path).query)
        if "/callback" in self.path and "code" in query_components:
            code = query_components["code"][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<h1>Success!</h1><p>You can close this window now. Check your terminal.</p>")
            
            # Use a global-ish way to pass the code back (this is a simple script)
            self.server.auth_code = code
        else:
            self.send_response(404)
            self.end_headers()

def main():
    load_dotenv()
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")

    if not client_id or not client_secret:
        logger.error("STRAVA_CLIENT_ID or STRAVA_CLIENT_SECRET not found in .env file.")
        sys.exit(1)

    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "read,activity:read_all,profile:read_all",
        "approval_prompt": "force"
    }
    
    auth_url_with_params = requests.Request('GET', AUTH_URL, params=params).prepare().url
    
    logger.info(f"Opening browser for Strava authorization...")
    logger.info(f"URL: {auth_url_with_params}")
    webbrowser.open(auth_url_with_params)

    server = HTTPServer(('localhost', PORT), OAuthCallbackHandler)
    server.auth_code = None
    
    logger.info(f"Waiting for callback on {REDIRECT_URI}...")
    while not server.auth_code:
        server.handle_request()

    code = server.auth_code
    logger.info(f"Received authorization code: {code}")

    # Exchange code for tokens
    logger.info("Exchanging code for tokens...")
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code"
    }
    
    response = requests.post(TOKEN_URL, data=payload)
    if response.status_code != 200:
        logger.error(f"Failed to exchange code: {response.text}")
        sys.exit(1)
        
    data = response.json()
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    expires_at = data.get("expires_at")

    logger.info("Authorization successful!")

    # Update config.json
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)
    else:
        logger.error(f"Config file not found at {CONFIG_PATH}. Please run main.py first to generate it or create it manually.")
        sys.exit(1)

    config["plugin_settings"]["access_token"] = access_token
    config["plugin_settings"]["refresh_token"] = refresh_token
    config["plugin_settings"]["token_expires_at"] = expires_at

    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
        
    logger.info(f"Tokens saved to {CONFIG_PATH}")

if __name__ == "__main__":
    main()
