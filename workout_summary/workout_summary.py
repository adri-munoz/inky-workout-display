from PIL import Image, ImageDraw, ImageFont
from utils.app_utils import get_font
import logging
import requests
import os
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# Activity type groupings for sport-specific totals
RUNNING_TYPES  = {'Run', 'TrailRun', 'Treadmill'}
CYCLING_TYPES  = {'Ride', 'VirtualRide', 'EBikeRide', 'MountainBikeRide', 'GravelRide'}
SWIMMING_TYPES = {'Swim'}
STRENGTH_TYPES = {'WeightTraining', 'Workout', 'Crossfit'}
TENNIS_TYPES   = {'Tennis'}
PADEL_TYPES    = {'Padel'}
RACKET_TYPES   = TENNIS_TYPES | PADEL_TYPES   # combined racket sports group
YOGA_TYPES     = {'Yoga'}


class WorkoutDisplay:
    """
    Renders a Strava activity summary image for the Inky Impression e-ink display.

    Displays aggregated totals for activities from Strava:
    - Total distance and moving time for all activities
    - Running-specific totals
    - Cycling-specific totals
    - Swimming-specific totals
    """

    def __init__(self, config):
        self.config = config

    def render(self, settings):
        """
        Generate and return a PIL image displaying Strava activity summaries.

        Args:
            settings (dict): Merged display and plugin settings plus Strava credentials.

        Returns:
            PIL.Image.Image: The rendered image to be displayed on the device.
        """
        # Get display dimensions
        dimensions = tuple(settings.get("resolution", [800, 480]))
        if settings.get("orientation", "horizontal") == "vertical":
            dimensions = dimensions[::-1]
        width, height = dimensions

        # Create image
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)

        try:
            # Get access token (with automatic refresh if needed)
            access_token = self._get_valid_access_token(settings)
            
            # Load configuration
            display_mode = settings.get("display_mode", "summary")
            time_mode = settings.get("time_mode", "rolling")
            days_back = int(settings.get("days_back", 7))
            time_type = settings.get("time_type", "moving_time")  # 'moving_time' or 'elapsed_time'
            
            # Calculate date range based on mode
            if time_mode == "current_week":
                display_start_date, period_label = get_current_week_start()
                # For API fetch, go back 1 second so "after" (exclusive) includes activities from Monday 00:00:00
                after_date = display_start_date - timedelta(seconds=1)
            else:
                # Include today in the range: if days_back=7, show past 6 days + today = 7 days total
                # Calculate the start of the first day we want to show
                display_start_date = datetime.now() - timedelta(days=days_back - 1)
                display_start_date = display_start_date.replace(hour=0, minute=0, second=0, microsecond=0)
                # For API fetch, go back 1 second so "after" (exclusive) includes the full start day
                after_date = display_start_date - timedelta(seconds=1)
                period_label = f"Last {days_back} Days" if days_back != 1 else "Today"

            # Fetch activities from Strava
            activities = fetch_strava_activities(access_token, after_date)

            if not activities:
                render_message(draw, width, height, "No activities found", period_label)
            else:
                # Aggregate activities using selected time type
                stats = aggregate_activities(activities, time_type)
                
                # Choose rendering mode
                if display_mode == "calendar":
                    # Calendar view with daily activities
                    render_calendar(draw, image, width, height, activities, display_start_date, period_label, time_type)
                elif display_mode == "combined":
                    # Combined view: summary + calendar
                    render_combined(draw, image, width, height, stats, activities, display_start_date, period_label, time_type)
                else:
                    # Summary view with aggregated totals
                    render_stats(draw, width, height, stats, period_label)

        except Exception as e:
            logger.error(f"Error fetching workout data: {e}")
            render_message(draw, width, height, "Workout Error", str(e))

        logger.debug(f"Workout plugin rendered image ({width}×{height})")
        return image

    def _get_valid_access_token(self, settings):
        """
        Get a valid access token, refreshing if necessary.
        
        Tries in this order:
        1. Token from settings (with automatic refresh)
        2. Token from environment variable (backward compatibility)
        
        Args:
            settings (dict): Plugin settings
            device_config: Device configuration
            
        Returns:
            str: Valid access token
            
        Raises:
            Exception: If no token available or refresh fails
        """
        # Check if we have tokens in settings
        access_token = settings.get("access_token")
        refresh_token = settings.get("refresh_token")
        expires_at = settings.get("token_expires_at")
        
        if access_token and expires_at:
            # Check if token is expired or about to expire (within 5 minutes)
            now = int(datetime.now().timestamp())
            if int(expires_at) > now + 300:
                logger.debug("Using valid access token from settings")
                return access_token
            
            # Token expired, try to refresh
            if refresh_token:
                logger.info("Access token expired, attempting refresh")
                try:
                    # Get client credentials from settings
                    client_id = settings.get("strava_client_id")
                    client_secret = settings.get("strava_client_secret")
                    
                    new_token = refresh_access_token(
                        client_id,
                        client_secret,
                        refresh_token
                    )
                    
                    # Update settings with new token (note: this may not persist automatically)
                    settings["access_token"] = new_token["access_token"]
                    settings["refresh_token"] = new_token["refresh_token"]
                    settings["token_expires_at"] = new_token["expires_at"]
                    
                    logger.info("Token refreshed successfully")
                    return new_token["access_token"]
                except Exception as e:
                    logger.error(f"Token refresh failed: {e}")
                    raise Exception("Token expired and refresh failed. Please re-authorize.")
        
        # Fall back to environment variable (backward compatibility)
        env_token = os.getenv("STRAVA_ACCESS_TOKEN")
        if env_token:
            logger.debug("Using access token from environment variable")
            return env_token
        
        # No token available
        raise Exception("No access token configured. Please authorize in settings.")


# ============================================================================
# STRAVA API CLIENT
# ============================================================================

def get_current_week_start():
    """
    Calculate the start of the current week (Monday).
    
    Returns:
        tuple: (start_datetime, label_string)
    """
    now = datetime.now()
    # weekday() returns 0=Monday, 6=Sunday
    days_since_monday = now.weekday()
    monday = now - timedelta(days=days_since_monday)
    # Set to beginning of Monday (00:00:00)
    monday_start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    return monday_start, "This week"


def fetch_strava_activities(access_token, after_date):
    """
    Fetch activities from Strava API for the specified time period.

    Args:
        access_token (str): Strava API access token
        after_date (datetime): Start date for fetching activities

    Returns:
        list: List of activity dictionaries from Strava API

    Raises:
        Exception: If API request fails
    """
    if not access_token:
        raise Exception("STRAVA_ACCESS_TOKEN not configured")

    # Convert to Unix timestamp for API
    after_timestamp = int(after_date.timestamp())

    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "after": after_timestamp,
        "per_page": 100  # Fetch up to 100 activities (can be extended with pagination)
    }

    url = "https://www.strava.com/api/v3/athlete/activities"
    response = requests.get(url, headers=headers, params=params, timeout=10)

    if response.status_code != 200:
        error_detail = ""
        try:
            error_data = response.json()
            error_detail = f": {error_data.get('message', '')}"
        except:
            pass
        
        if response.status_code == 401:
            raise Exception(f"Token invalid or expired{error_detail}")
        else:
            raise Exception(f"API returned {response.status_code}{error_detail}")

    activities = response.json()
    logger.info(f"Fetched {len(activities)} activities from Strava")
    return activities


def refresh_access_token(client_id, client_secret, refresh_token):
    """
    Refresh an expired Strava access token.
    
    Args:
        client_id (str): Strava API client ID
        client_secret (str): Strava API client secret
        refresh_token (str): Refresh token
        
    Returns:
        dict: New token data with keys: access_token, refresh_token, expires_at
        
    Raises:
        Exception: If refresh fails
    """
    if not all([client_id, client_secret, refresh_token]):
        raise Exception("Client credentials and refresh token required")
    
    response = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        },
        timeout=10
    )
    
    if response.status_code != 200:
        raise Exception(f"Token refresh failed: {response.status_code}")
    
    return response.json()


# ============================================================================
# AGGREGATION LOGIC
# ============================================================================

def aggregate_activities(activities, time_field='moving_time'):
    """
    Aggregate activity data into sport-specific and overall totals.

    Args:
        activities (list): List of Strava activity dictionaries
        time_field (str): Which time field to use - 'moving_time' or 'elapsed_time'

    Returns:
        dict: Aggregated statistics with keys:
            - total_km, total_time_seconds
            - run_km, run_time_seconds
            - bike_km, bike_time_seconds
            - swim_km, swim_time_seconds
            - strength_time_seconds
    """
    stats = {
        'total_km': 0.0,
        'total_time_seconds': 0,
        'run_km': 0.0,
        'run_time_seconds': 0,
        'run_days': 0,
        'bike_km': 0.0,
        'bike_time_seconds': 0,
        'bike_days': 0,
        'swim_km': 0.0,
        'swim_time_seconds': 0,
        'swim_days': 0,
        'strength_time_seconds': 0,
        'strength_days': 0,
        'racket_time_seconds': 0,
        'racket_days': 0,
        'yoga_time_seconds': 0,
        'yoga_days': 0,
    }

    # Track unique days per sport type using sets
    run_day_set      = set()
    bike_day_set     = set()
    swim_day_set     = set()
    strength_day_set = set()
    racket_day_set   = set()
    yoga_day_set     = set()

    for activity in activities:
        # Safely extract fields (handle missing data)
        distance_meters = activity.get('distance', 0) or 0
        activity_time = activity.get(time_field, 0) or 0  # Use selected time field
        sport_type = activity.get('sport_type') or activity.get('type', '')

        # Extract day string for day counting
        date_str = activity.get('start_date_local') or activity.get('start_date', '')
        day_key = date_str[:10] if date_str else None  # e.g. "2026-03-10"

        # Add to overall totals
        stats['total_km'] += meters_to_km(distance_meters)
        stats['total_time_seconds'] += activity_time

        # Add to sport-specific totals
        if sport_type in RUNNING_TYPES:
            stats['run_km'] += meters_to_km(distance_meters)
            stats['run_time_seconds'] += activity_time
            if day_key:
                run_day_set.add(day_key)
        elif sport_type in CYCLING_TYPES:
            stats['bike_km'] += meters_to_km(distance_meters)
            stats['bike_time_seconds'] += activity_time
            if day_key:
                bike_day_set.add(day_key)
        elif sport_type in SWIMMING_TYPES:
            stats['swim_km'] += meters_to_km(distance_meters)
            stats['swim_time_seconds'] += activity_time
            if day_key:
                swim_day_set.add(day_key)
        elif sport_type in STRENGTH_TYPES:
            # Strength training doesn't have distance
            stats['strength_time_seconds'] += activity_time
            if day_key:
                strength_day_set.add(day_key)
        elif sport_type in RACKET_TYPES:
            stats['racket_time_seconds'] += activity_time
            if day_key:
                racket_day_set.add(day_key)
        elif sport_type in YOGA_TYPES:
            stats['yoga_time_seconds'] += activity_time
            if day_key:
                yoga_day_set.add(day_key)

    stats['run_days']      = len(run_day_set)
    stats['bike_days']     = len(bike_day_set)
    stats['swim_days']     = len(swim_day_set)
    stats['strength_days'] = len(strength_day_set)
    stats['racket_days'] = len(racket_day_set)
    stats['yoga_days']   = len(yoga_day_set)

    return stats


def group_activities_by_day(activities, start_date, time_field='moving_time'):
    """
    Group activities by day for calendar view.
    
    Args:
        activities (list): List of Strava activity dictionaries
        start_date (datetime): Start date for the period
        time_field (str): Which time field to use - 'moving_time' or 'elapsed_time'
        
    Returns:
        dict: Dictionary mapping date strings (YYYY-MM-DD) to lists of activity dicts
              Example: {'2026-03-10': [{'type': 'Run', 'duration': 3600}, {'type': 'Bike', 'duration': 7200}]}
    """
    from datetime import datetime
    from collections import defaultdict
    
    # Create dict with empty lists for each day in the range
    days_dict = defaultdict(list)
    
    for activity in activities:
        # Get activity date (use start_date_local if available)
        date_str = activity.get('start_date_local') or activity.get('start_date', '')
        if not date_str:
            continue
            
        # Parse date (format: 2026-03-10T08:30:00Z)
        try:
            activity_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            date_key = activity_date.strftime('%Y-%m-%d')
            
            # Determine activity type icon name
            sport_type = activity.get('sport_type') or activity.get('type', '')
            activity_time = activity.get(time_field, 0) or 0  # Use selected time field
            distance_meters = activity.get('distance', 0) or 0
            
            if sport_type in RUNNING_TYPES:
                icon_name = 'Run'
            elif sport_type in CYCLING_TYPES:
                icon_name = 'Bike'
            elif sport_type in SWIMMING_TYPES:
                icon_name = 'Swim'
            elif sport_type in STRENGTH_TYPES:
                icon_name = 'Strength'
            elif sport_type in RACKET_TYPES:
                icon_name = 'Tennis'
            elif sport_type in YOGA_TYPES:
                icon_name = 'Yoga'
            else:
                continue  # Skip other activity types

            # Sports with no distance
            no_distance = STRENGTH_TYPES | RACKET_TYPES | YOGA_TYPES
            dist_km = meters_to_km(distance_meters) if sport_type not in no_distance else 0

            # Deduplicate: if this sport already has an entry for this day, merge it
            existing = next((e for e in days_dict[date_key] if e['type'] == icon_name), None)
            if existing:
                existing['duration']    += activity_time
                existing['distance_km'] += dist_km
            else:
                days_dict[date_key].append({
                    'type':        icon_name,
                    'duration':    activity_time,
                    'distance_km': dist_km,
                })
                
        except Exception as e:
            logger.warning(f"Could not parse activity date: {date_str}, {e}")
            continue
    
    return days_dict


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def meters_to_km(meters):
    """Convert meters to kilometers."""
    return meters / 1000.0


def format_duration(seconds):
    """Format duration in seconds as 'z min' for <1h, or 'x h z m' for >=1h."""
    total_minutes = max(0, seconds) // 60
    if total_minutes >= 60:
        h = total_minutes // 60
        m = total_minutes % 60
        return f"{h} h {m} m"
    return f"{total_minutes} min"


# ============================================================================
# RENDERING
# ============================================================================

def load_activity_icon(icon_name, target_height):
    """
    Load and resize an activity icon from the images folder.
    
    Args:
        icon_name (str): Name of the icon (e.g., "Run", "Bike", "Swim")
        target_height (int): Target height for the icon (width scales proportionally)
        
    Returns:
        PIL.Image or None: Resized icon image, or None if not found
    """
    try:
        # Get the path to the images folder (inside the plugin folder)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(current_dir, "images", f"{icon_name}.png")
        
        if os.path.exists(icon_path):
            if target_height <= 0:
                logger.warning(f"Icon {icon_name} skipped: target_height={target_height}")
                return None
            icon = Image.open(icon_path)

            # Calculate new width to maintain aspect ratio
            aspect_ratio = icon.width / icon.height
            new_width = max(1, int(target_height * aspect_ratio))
            
            # Resize maintaining aspect ratio
            icon = icon.resize((new_width, target_height), Image.LANCZOS)
            
            # Keep as RGBA to preserve colors and transparency
            if icon.mode != 'RGBA':
                icon = icon.convert('RGBA')
            return icon
    except Exception as e:
        import traceback
        logger.warning(f"Could not load icon {icon_name}: {e}\n{traceback.format_exc()}")
    return None


def render_stats(draw, width, height, stats, period_label):
    """
    Render aggregated Strava statistics on the image with Strava-inspired design.

    Args:
        draw: PIL ImageDraw object
        width (int): Image width
        height (int): Image height
        stats (dict): Aggregated statistics
        period_label (str): Label for the time period (e.g., "7d" or "This week")
    """
    # Get the base image for pasting icons
    image = draw._image
    
    # Strava brand color (converted to grayscale for e-ink: use dark gray for accent)
    strava_accent = "#333333"  # Dark gray works better on e-ink than orange
    text_primary = "black"
    text_secondary = "#666666"
    
    # Font sizes - Strava uses bold numbers with smaller labels
    header_size = int(width * 0.045)
    big_number_size = int(width * 0.08)  # Large, bold numbers
    small_number_size = int(width * 0.05)
    tiny_label_size = int(width * 0.028)
    
    header_font = get_font("DM Sans", header_size)
    big_font = get_font("DM Sans", big_number_size)
    number_font = get_font("DM Sans", small_number_size)
    label_font = get_font("DM Sans", tiny_label_size)
    
    padding = int(width * 0.05)
    y_pos = padding * 2  # Start lower
    
    # Header with period
    draw.text((padding, y_pos), period_label.upper(), fill=strava_accent, font=header_font)
    y_pos += header_size + int(padding * 0.4) 
    
    # Draw a subtle line under header
    line_y = y_pos
    draw.line([(padding, line_y), (width - padding, line_y)], fill="#CCCCCC", width=2)
    y_pos += int(padding ) 
    
    # Main stats section - emphasize total with big numbers
    if stats['total_km'] > 0:
        # "Total" label
        draw.text((padding, y_pos), "Total", fill=text_secondary, font=label_font)
        y_pos += tiny_label_size + int(padding * 0.4)
        
        # Big total distance
        distance_text = f"{stats['total_km']:.1f}"
        draw.text((padding, y_pos), distance_text, fill=text_primary, font=big_font)
        
        # Unit label next to number (baseline aligned)
        bbox = draw.textbbox((0, 0), distance_text, font=big_font)
        text_width = bbox[2] - bbox[0]
        draw.text((padding + text_width + 5, y_pos + big_number_size - tiny_label_size - 5), 
                  "km", fill=text_secondary, font=label_font)
        
        y_pos += big_number_size + int(padding * 1.0)  # Increased from 0.2 to 1.0
        
        # Total time below
        time_text = format_duration(stats['total_time_seconds'])
        draw.text((padding, y_pos), time_text, fill=text_secondary, font=number_font)
        y_pos += number_font.size + int(padding * 2.5)  # Increased from 1.2 to 2.5
    
    # Activity breakdown - compact grid layout with icons
    activities = []
    if stats['run_km'] > 0:
        activities.append(("Run", "RUN", stats['run_km'], stats['run_time_seconds'], stats['run_days']))
    if stats['bike_km'] > 0:
        activities.append(("Bike", "RIDE", stats['bike_km'], stats['bike_time_seconds'], stats['bike_days']))
    if stats['swim_km'] > 0:
        activities.append(("Swim", "SWIM", stats['swim_km'], stats['swim_time_seconds'], stats['swim_days']))
    if stats['strength_time_seconds'] > 0:
        activities.append(("Strength", "STRENGTH", 0, stats['strength_time_seconds'], stats['strength_days']))
    
    if activities:
        # Draw separator line
        draw.line([(padding, y_pos), (width - padding, y_pos)], fill="#CCCCCC", width=1)
        y_pos += int(padding * 2.0)  # Increased from 0.8 to 2.0

        # Icon size for activities
        icon_size = int(tiny_label_size * 1.5)

        # Grid layout for activities
        col_width = (width - 2 * padding) // min(len(activities), 3)

        for i, (icon_name, label_text, km, seconds, days) in enumerate(activities):
            # Calculate position (up to 3 columns)
            col = i % 3
            row = i // 3
            x_pos = padding + (col * col_width)
            current_y = y_pos + (row * int(padding * 6.0))  # Increased from 3.5 to 6.0

            # Load and place activity icon
            icon = load_activity_icon(icon_name, icon_size)
            if icon:
                image.paste(icon, (x_pos, current_y), icon)
                # Label next to icon
                draw.text((x_pos + icon_size + 5, current_y), label_text,
                         fill=text_secondary, font=label_font)
                current_y += icon_size + 10  # Increased from 5 to 10
            else:
                # Fallback to text if icon not found
                draw.text((x_pos, current_y), label_text, fill=text_secondary, font=label_font)
                current_y += tiny_label_size + 10  # Increased from 5 to 10

            # Distance (skip for activities with no distance like strength training)
            if km > 0:
                distance = f"{km:.1f}"
                draw.text((x_pos, current_y), distance, fill=text_primary, font=number_font)

                # Unit
                bbox = draw.textbbox((0, 0), distance, font=number_font)
                dist_width = bbox[2] - bbox[0]
                draw.text((x_pos + dist_width + 3, current_y + 3), "km",
                         fill=text_secondary, font=label_font)
                current_y += number_font.size + 6  # Increased from 3 to 6

            # Time
            time_str = format_duration(seconds)
            draw.text((x_pos, current_y), time_str, fill=text_secondary, font=label_font)
            current_y += tiny_label_size + 4

            # Days
            day_label = "1 day" if days == 1 else f"{days} days"
            draw.text((x_pos, current_y), day_label, fill=text_secondary, font=label_font)


def render_calendar(draw, image, width, height, activities, start_date, period_label, time_field='moving_time'):
    """
    Render a calendar view showing daily activities with icons and durations.
    
    Args:
        draw: PIL ImageDraw object
        image: PIL Image object (for pasting icons)
        width (int): Image width
        height (int): Image height
        activities (list): List of activity dictionaries from Strava
        start_date (datetime): Start date for the calendar
        period_label (str): Label for the time period
        time_field (str): Which time field to use - 'moving_time' or 'elapsed_time'
    """
    text_primary = "black"
    text_secondary = "#666666"
    
    # Font sizes
    header_size = int(width * 0.045)
    day_label_size = int(width * 0.035)
    date_size = int(width * 0.032)
    duration_size = int(width * 0.025)
    
    header_font = get_font("DM Sans", header_size)
    day_font = get_font("DM Sans", day_label_size)
    date_font = get_font("DM Sans", date_size)
    duration_font = get_font("DM Sans", duration_size)
    
    padding = int(width * 0.05)  # Increased from 0.03 to 0.05
    y_pos = padding * 2  # Start lower
    
    # Header with period
    draw.text((padding, y_pos), period_label.upper(), fill=text_primary, font=header_font)
    y_pos += header_size + int(padding * 1.5)  # Increased from 0.5 to 1.5
    
    # Draw separator line
    draw.line([(padding, y_pos), (width - padding, y_pos)], fill="#CCCCCC", width=2)
    y_pos += int(padding * 2.0)  # Increased from 0.8 to 2.0
    
    # Group activities by day
    activities_by_day = group_activities_by_day(activities, start_date)
    
    # Generate 7 days starting from start_date
    days = []
    current = start_date
    for i in range(7):
        days.append(current + timedelta(days=i))
    
    # Calculate column width for 7 days
    col_width = (width - 2 * padding) // 7
    icon_size = int(col_width * 0.5)  # Icons sized to fit in column
    icon_size = min(icon_size, int(height * 0.15))  # Cap at 15% of height
    
    # Render each day column
    for i, day in enumerate(days):
        x_pos = padding + (i * col_width)
        current_y = y_pos
        
        # Day of week (Mon, Tue, etc.)
        day_name = day.strftime('%a').upper()
        draw.text((x_pos, current_y), day_name, fill=text_secondary, font=day_font)
        current_y += day_label_size + 8  # Increased from 3 to 8
        
        # Date (10)
        day_number = day.strftime('%d')
        draw.text((x_pos, current_y), day_number, fill=text_primary, font=date_font)
        current_y += date_size + int(padding * 1.5)  # Increased from 0.5 to 1.5
        
        # Activity icons for this day
        date_key = day.strftime('%Y-%m-%d')
        day_activities = activities_by_day.get(date_key, [])
        
        if day_activities:
            # Stack icons vertically under the date with duration and distance
            for activity_data in day_activities[:3]:  # Max 3 activities per day
                activity_type = activity_data['type']
                duration = activity_data['duration']
                distance_km = activity_data['distance_km']
                
                icon = load_activity_icon(activity_type, icon_size)
                if icon:
                    # Center icon in column (calculate center of column)
                    col_center_x = x_pos + (col_width // 2)
                    icon_x = col_center_x - (icon.width // 2)
                    image.paste(icon, (icon_x, current_y), icon)
                    current_y += icon.height + 6  # Increased from 2 to 6
                    
                    # Add distance below icon (skip for activities with no distance like strength)
                    if distance_km > 0:
                        distance_text = f"{distance_km:.1f} km"
                        bbox = draw.textbbox((0, 0), distance_text, font=duration_font)
                        distance_width = bbox[2] - bbox[0]
                        distance_x = col_center_x - (distance_width // 2)
                        draw.text((distance_x, current_y), distance_text, fill=text_primary, font=duration_font)
                        current_y += duration_size + 4  # Increased from 1 to 4
                    
                    # Add duration below distance (or below icon for strength)
                    duration_text = format_duration(duration)
                    bbox = draw.textbbox((0, 0), duration_text, font=duration_font)
                    duration_width = bbox[2] - bbox[0]
                    duration_x = col_center_x - (duration_width // 2)
                    draw.text((duration_x, current_y), duration_text, fill=text_secondary, font=duration_font)
                    current_y += duration_size + 15  # Increased from 5 to 15
        else:
            # Show a dot or dash for no activities
            dash_y = current_y + icon_size // 2
            col_center_x = x_pos + (col_width // 2)
            draw.line([(col_center_x - 5, dash_y), 
                      (col_center_x + 5, dash_y)], 
                     fill="#CCCCCC", width=2)


def render_combined(draw, image, width, height, stats, activities, start_date, period_label, time_field='moving_time'):
    """
    Render combined view: 2-row × 3-col summary grid + 7-day calendar.
    Layout matches the approved mockup design.
    """
    PAD        = 28
    usable_w   = width - 2 * PAD
    BLACK      = "#111111"
    DARK_GREY  = "#444444"
    MID_GREY   = "#888888"
    LIGHT_GREY = "#D0D0D0"
    ORANGE     = "#FC4C02"

    f_title = get_font("DM Sans", 36, "bold")
    f_name  = get_font("DM Sans", 28, "bold")
    f_day   = get_font("DM Sans", 20, "bold")
    f_date  = get_font("DM Sans", 26)

    def _tw(text, fnt):
        bb = draw.textbbox((0, 0), text, font=fnt)
        return bb[2] - bb[0]

    def _th_ref(fnt, ref="Ag"):
        bb = draw.textbbox((0, 0), ref, font=fnt)
        return bb[3] - bb[1]

    # ── HEADER ────────────────────────────────────────────────────────────────
    HEADER_H = 70

    _bb     = draw.textbbox((0, 0), period_label.upper(), font=f_title)
    title_x = (width - (_bb[2] - _bb[0])) // 2
    title_y = (HEADER_H - _bb[1] - _bb[3]) // 2
    draw.text((title_x, title_y), period_label.upper(), fill=BLACK, font=f_title)

    # ── SUMMARY GRID ──────────────────────────────────────────────────────────
    SUMMARY_TOP = HEADER_H + 3
    CAL_H       = 125                            # calendar: always this fixed height
    CAL_TOP     = height - CAL_H
    SUMMARY_BOT = CAL_TOP - 2
    CELL_W      = usable_w // 3

    # Build list of active sports in display order
    summary = []
    if stats.get('run_time_seconds', 0) > 0:
        summary.append(("Run",      "Run",      stats['run_days'],      stats['run_time_seconds'],      stats.get('run_km', 0)))
    if stats.get('bike_time_seconds', 0) > 0:
        summary.append(("Bike",     "Ride",     stats['bike_days'],     stats['bike_time_seconds'],     stats.get('bike_km', 0)))
    if stats.get('swim_time_seconds', 0) > 0:
        summary.append(("Swim",     "Swim",     stats['swim_days'],     stats['swim_time_seconds'],     stats.get('swim_km', 0)))
    if stats.get('racket_time_seconds', 0) > 0:
        summary.append(("Tennis",   "Racket",   stats['racket_days'],   stats['racket_time_seconds'],   0))
    if stats.get('strength_time_seconds', 0) > 0:
        summary.append(("Strength", "Strength", stats['strength_days'], stats['strength_time_seconds'], 0))
    if stats.get('yoga_time_seconds', 0) > 0:
        summary.append(("Yoga",     "Yoga",     stats['yoga_days'],     stats['yoga_time_seconds'],     0))

    # Dynamic layout: scale all summary internals to fill available cell height
    # Baseline: CELL_H=140 → ICON_H=52, GAP1=14, GAP2=12, stats font 22
    num_rows = max(1, (len(summary) + 2) // 3)
    CELL_H   = (SUMMARY_BOT - SUMMARY_TOP) // num_rows
    ICON_H   = min(100, max(52, CELL_H * 52 // 140))
    GAP1     = max(14, CELL_H * 14 // 140)
    GAP2     = max(12, CELL_H * 12 // 140)
    f_stats  = get_font("DM Sans", max(22, min(32, 22 * CELL_H // 140)))
    stats_h  = _th_ref(f_stats, "2x")

    for idx, (icon_name, label, days, seconds, km) in enumerate(summary):
        row    = idx // 3
        col    = idx % 3
        cell_x = PAD + col * CELL_W
        cell_y = SUMMARY_TOP + row * CELL_H

        # icon on top, centred; stats below
        has_dist = km > 0
        block_h  = ICON_H + GAP1 + stats_h + (GAP2 + stats_h if has_dist else 0)
        start_y  = cell_y + (CELL_H - block_h) // 2

        icon = load_activity_icon(icon_name, ICON_H)
        if icon:
            image.paste(icon, (cell_x + (CELL_W - icon.width) // 2, start_y), icon)

        line1_y   = start_y + ICON_H + GAP1
        count_str = f"{days}x"
        time_str  = f"  ·  {format_duration(seconds)}"
        line1_w   = _tw(count_str, f_stats) + _tw(time_str, f_stats)
        line1_x   = cell_x + (CELL_W - line1_w) // 2
        draw.text((line1_x, line1_y), count_str, fill=ORANGE, font=f_stats)
        draw.text((line1_x + _tw(count_str, f_stats), line1_y),
                  time_str, fill=DARK_GREY, font=f_stats)

        if has_dist:
            dist_str = f"{km:.1f} km"
            line2_x  = cell_x + (CELL_W - _tw(dist_str, f_stats)) // 2
            draw.text((line2_x, line1_y + stats_h + GAP2),
                      dist_str, fill=DARK_GREY, font=f_stats)

    draw.line([(0, SUMMARY_BOT), (width, SUMMARY_BOT)], fill=BLACK, width=2)

    # ── CALENDAR ──────────────────────────────────────────────────────────────
    COL_W = usable_w // 7

    DAY_H      = 25
    DATE_H     = 30
    TOP_PAD    = 10
    TEXT_BLOCK = TOP_PAD + DAY_H + 4 + DATE_H + 10
    icon_area  = CAL_H - TEXT_BLOCK
    CAL_ICON_H = min(65, icon_area)                  # fill available height; icons are square
    CAN_STACK  = icon_area >= CAL_ICON_H * 2 + 6    # room for 2 stacked icons?

    activities_by_day = group_activities_by_day(activities, start_date, time_field)

    for i in range(7):
        day      = start_date + timedelta(days=i)
        date_key = day.strftime('%Y-%m-%d')
        col_x    = PAD + i * COL_W
        col_cx   = col_x + COL_W // 2

        cur_y = CAL_TOP + TOP_PAD

        # day name ("MON")
        day_name = day.strftime('%a').upper()
        draw.text((col_cx - _tw(day_name, f_day) // 2, cur_y),
                  day_name, fill=ORANGE, font=f_day)
        cur_y += DAY_H + 4

        # date number
        date_str = day.strftime('%-d')
        draw.text((col_cx - _tw(date_str, f_date) // 2, cur_y),
                  date_str, fill=BLACK, font=f_date)
        cur_y += DATE_H + 10

        # activity icons (max 2, already deduplicated per sport type)
        day_acts = activities_by_day.get(date_key, [])[:2]
        if day_acts:
            icons = [load_activity_icon(act['type'], CAL_ICON_H) for act in day_acts]
            icons = [ic for ic in icons if ic]
            if len(icons) == 2 and not CAN_STACK:
                # side-by-side: not enough vertical room to stack
                gap   = 4
                row_w = sum(ic.width for ic in icons) + gap
                sx    = col_cx - row_w // 2
                iy    = cur_y + (icon_area - CAL_ICON_H) // 2
                for ic in icons:
                    image.paste(ic, (sx, iy), ic)
                    sx += ic.width + gap
            else:
                for ic in icons:
                    image.paste(ic, (col_cx - ic.width // 2, cur_y), ic)
                    cur_y += CAL_ICON_H + 6
        else:
            dy = cur_y + icon_area // 2
            draw.line([(col_cx - 12, dy), (col_cx + 12, dy)], fill=DARK_GREY, width=2)


# Legacy render mode — kept for backwards compatibility but layout is unchanged
def _render_combined_legacy(draw, image, width, height, stats, activities, start_date, period_label, time_field='moving_time'):
    text_primary = "black"
    text_secondary = "#FC4C02"  # Strava orange

    # Font sizes - give more space to summary section
    header_size = int(width * 0.045)
    stat_size = int(width * 0.055)
    tiny_size = int(width * 0.032)
    day_label_size = int(width * 0.028)

    header_font = get_font("DM Sans", header_size)
    stat_font = get_font("DM Sans", stat_size)
    tiny_font = get_font("DM Sans", tiny_size)
    day_font = get_font("DM Sans", day_label_size)
    
    padding = int(width * 0.05)
    y_pos = int(padding * 0.4)

    # Header
    draw.text((padding, y_pos), period_label.upper(), fill=text_primary, font=header_font)
    y_pos += header_size + int(padding * 0.5)

    # Separator
    draw.line([(padding, y_pos), (width - padding, y_pos)], fill="#CCCCCC", width=1)
    y_pos += int(padding * 0.5)

    # Summary stats
    if stats['total_km'] > 0:
        # Three equal columns, same font size, each centered
        col_w = (width - 2 * padding) // 3
        for i, (text, color) in enumerate([
            ("Total", text_secondary),
            (f"{stats['total_km']:.1f} km", text_primary),
            (format_duration(stats['total_time_seconds']), text_primary),
        ]):
            col_center = padding + i * col_w + col_w // 2
            bbox = draw.textbbox((0, 0), text, font=stat_font)
            draw.text((col_center - (bbox[2] - bbox[0]) // 2, y_pos), text, fill=color, font=stat_font)
        y_pos += stat_size + int(padding * 0.5)

        # Activity breakdown
        activities_summary = []
        if stats['run_km'] > 0:
            activities_summary.append(("Run", stats['run_km'], stats['run_time_seconds'], stats['run_days']))
        if stats['bike_km'] > 0:
            activities_summary.append(("Bike", stats['bike_km'], stats['bike_time_seconds'], stats['bike_days']))
        if stats['swim_km'] > 0:
            activities_summary.append(("Swim", stats['swim_km'], stats['swim_time_seconds'], stats['swim_days']))
        if stats['strength_time_seconds'] > 0:
            activities_summary.append(("Strength", 0, stats['strength_time_seconds'], stats['strength_days']))

        if activities_summary:
            icon_size = int(tiny_size * 1.8)
            col_width = (width - 2 * padding) // len(activities_summary)

            for i, (activity_icon, km, seconds, days) in enumerate(activities_summary):
                x_offset = padding + (i * col_width)
                current_y = y_pos

                # Icon
                icon = load_activity_icon(activity_icon, icon_size)
                if icon:
                    image.paste(icon, (x_offset, current_y), icon)
                    current_y += icon.height + 10

                # Time · Days on top
                time_day_text = f"{format_duration(seconds)} · {days}x"
                draw.text((x_offset, current_y), time_day_text, fill=text_secondary, font=tiny_font)
                current_y += tiny_size + 10

                # Distance on bottom (skip for strength)
                if km > 0:
                    draw.text((x_offset, current_y), f"{km:.1f} km", fill=text_primary, font=tiny_font)

            y_pos += icon_size + (tiny_size * 2) + 40  # 20px internal gaps + 20px before separator

    # Separator before calendar
    draw.line([(padding, y_pos), (width - padding, y_pos)], fill="#CCCCCC", width=2)
    y_pos += int(padding * 0.25)
    
    # Calendar section
    # Group activities by day
    activities_by_day = group_activities_by_day(activities, start_date, time_field)
    
    # Generate 7 days
    days = []
    current = start_date
    for i in range(7):
        days.append(current + timedelta(days=i))
    
    # Calculate column width for 7 days
    col_width = (width - 2 * padding) // 7
    icon_size = min(int(col_width * 0.6), int((height - y_pos) * 0.5))
    icon_size = max(icon_size, 1)

    # Vertically center [day_name + gap + icon] block in remaining space
    cal_content_height = day_label_size + 8 + icon_size
    cal_top_margin = max(0, (height - y_pos - cal_content_height) // 2)

    # Render each day column
    for i, day in enumerate(days):
        x_pos = padding + (i * col_width)
        col_center_x = x_pos + (col_width // 2)
        current_y = y_pos + cal_top_margin

        # Day name centered
        day_name = day.strftime('%a').upper()
        bbox = draw.textbbox((0, 0), day_name, font=day_font)
        draw.text((col_center_x - (bbox[2] - bbox[0]) // 2, current_y), day_name, fill=text_secondary, font=day_font)
        current_y += day_label_size + 8

        # Activity icons for this day
        date_key = day.strftime('%Y-%m-%d')
        day_activities = activities_by_day.get(date_key, [])

        if day_activities:
            shown = day_activities[:2]
            icons = [load_activity_icon(a['type'], icon_size) for a in shown]
            icons = [ic for ic in icons if ic]
            if icons:
                total_w = sum(ic.width for ic in icons) + 4 * (len(icons) - 1)
                start_x = col_center_x - total_w // 2
                for ic in icons:
                    image.paste(ic, (start_x, current_y), ic)
                    start_x += ic.width + 4
        else:
            dash_y = current_y + icon_size // 2
            draw.line([(col_center_x - 4, dash_y), (col_center_x + 4, dash_y)],
                      fill="#CCCCCC", width=2)


def render_message(draw, width, height, line1, line2):
    """
    Render a simple message with Strava-inspired styling (used for errors or empty states).

    Args:
        draw: PIL ImageDraw object
        width (int): Image width
        height (int): Image height
        line1 (str): First line of message (header)
        line2 (str): Second line of message (detail)
    """
    padding = int(width * 0.04)
    title_size = int(width * 0.06)
    subtitle_size = int(width * 0.04)
    
    title_font = get_font("DM Sans", title_size)
    subtitle_font = get_font("DM Sans", subtitle_size)
    
    # Draw a border box
    box_padding = padding * 2
    box_top = height // 3
    box_height = int(height * 0.35)
    
    # Light gray box background effect (just borders for e-ink)
    draw.rectangle(
        [(box_padding, box_top), (width - box_padding, box_top + box_height)],
        outline="#999999",
        width=2
    )
    
    # Center first line (title)
    bbox = draw.textbbox((0, 0), line1, font=title_font)
    text_width = bbox[2] - bbox[0]
    x = (width - text_width) // 2
    y = box_top + int(box_height * 0.25)
    
    draw.text((x, y), line1, fill="black", font=title_font)

    # Center second line (subtitle)
    if line2:
        bbox2 = draw.textbbox((0, 0), line2, font=subtitle_font)
        text_width2 = bbox2[2] - bbox2[0]
        x2 = (width - text_width2) // 2
        y2 = y + int(title_size * 1.5)
        draw.text((x2, y2), line2, fill="#666666", font=subtitle_font)
