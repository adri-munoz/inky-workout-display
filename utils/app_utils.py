import os
from PIL import ImageFont
import logging

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FONTS_DIR = os.environ.get("FONTS_DIR", os.path.join(_PROJECT_ROOT, "fonts"))

FONT_FAMILIES = {
    "DM Sans": [
        {"font-weight": "normal", "file": "DMSans-Regular.ttf"},
        {"font-weight": "bold",   "file": "DMSans-SemiBold.ttf"},
    ]
}

def get_font(font_name, font_size=50, font_weight="normal"):
    variants = FONT_FAMILIES.get(font_name)
    if not variants:
        logger.warning(f"Font not found: {font_name}")
        return None
    entry = next((v for v in variants if v["font-weight"] == font_weight), variants[0])
    font_path = os.path.join(_FONTS_DIR, entry["file"])
    try:
        return ImageFont.truetype(font_path, font_size)
    except Exception as e:
        logger.error(f"Could not load font {font_path}: {e}")
        return None
