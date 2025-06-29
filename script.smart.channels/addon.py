import xbmcvfs
import xbmcgui
import xbmc
import json
import urllib.parse
import xml.etree.ElementTree as ET
import random
import os
import sqlite3
import xbmcaddon
from datetime import datetime
import threading

# Global addon variables
addon = xbmcaddon.Addon()
addon_name = addon.getAddonInfo("name")
addon_id = addon.getAddonInfo("id")
data_path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
settings_file = os.path.join(data_path, "settings.json")
channels_file = os.path.join(data_path, "channels.json")
channel_lock = threading.Lock()

# Get the addon instance and basic info
#addon = xbmcaddon.Addon()
#addon_name = addon.getAddonInfo('name')
#addon_id = addon.getAddonInfo('id')

# Path to addon data folder (special://profile/addon_data/script.smart.channels/)
#data_path = xbmcvfs.translatePath(f"special://profile/addon_data/{addon_id}/")
#channels_file = os.path.join(data_path, "channels.json")
#settings_file = os.path.join(data_path, "settings.json")

# Ensure addon data folder exists
if not xbmcvfs.exists(data_path):
    try:
        xbmcvfs.mkdirs(data_path)
        xbmc.log(f"{addon_name}: Created addon data folder: {data_path}", level=xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f"{addon_name}: Failed to create addon data folder: {str(e)}", level=xbmc.LOGERROR)

def load_settings():
    """Load settings from settings.json. Returns dict with defaults on failure."""
    try:
        if xbmcvfs.exists(settings_file):
            with xbmcvfs.File(settings_file, 'r') as f:
                return json.load(f)
        return {"playlist_upper_limit": 50}
    except Exception as e:
        xbmc.log(f"{addon_name}: Failed to load settings: {str(e)}", level=xbmc.LOGERROR)
        return {"playlist_upper_limit": 50}

def save_settings(settings):
    """Save settings to settings.json."""
    try:
        with xbmcvfs.File(settings_file, 'w') as f:
            json.dump(settings, f, indent=4)
        xbmc.log(f"{addon_name}: Saved settings to {settings_file}", level=xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f"{addon_name}: Failed to save settings: {str(e)}", level=xbmc.LOGERROR)
        xbmcgui.Dialog().ok(addon_name, "Failed to save settings. Check kodi.log for details.")

def load_channels():
    """Load channels from channels.json, sorting by channel number. Returns empty list on failure."""
    try:
        if xbmcvfs.exists(channels_file):
            with xbmcvfs.File(channels_file, 'r') as f:
                channels = json.load(f)
                # Sort channels by number (convert to int for proper numeric sorting)
                return sorted(channels, key=lambda x: int(x['number']) if x['number'].isdigit() else float('inf'))
        return []
    except Exception as e:
        xbmc.log(f"{addon_name}: Failed to load channels: {str(e)}", level=xbmc.LOGERROR)
        return []

def save_channels(channels):
    """Save channels to channels.json, sorting by channel number."""
    try:
        # Sort channels by number before saving
        channels = sorted(channels, key=lambda x: int(x['number']) if x['number'].isdigit() else float('inf'))
        with xbmcvfs.File(channels_file, 'w') as f:
            json.dump(channels, f, indent=4)
        xbmc.log(f"{addon_name}: Saved channels to {channels_file}", level=xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f"{addon_name}: Failed to save channels: {str(e)}", level=xbmc.LOGERROR)
        xbmcgui.Dialog().ok(addon_name, "Failed to save channels. Check kodi.log for details.")
        
# Updated function for Delete All Channels
def delete_all_channels():
    """Delete all channels from channels.json and their associated M3U files."""
    dialog = xbmcgui.Dialog()
    addon = xbmcaddon.Addon()
    addon_name = addon.getAddonInfo('name')
    
    # Show confirmation dialog (Kodi Omega compatible)
    confirm = dialog.yesno(heading=addon_name, message="Are You Sure?\nThis will delete all created channels and their M3U files.", yeslabel="Yes", nolabel="No")
    
    if confirm:
        # Load channels to get their numbers
        channels = load_channels()
        addon_data_path = xbmcvfs.translatePath('special://profile/addon_data/script.smart.channels/')
        
        # Delete associated M3U files
        for channel in channels:
            m3u_path = os.path.join(addon_data_path, f"channel_{channel['number']}.m3u")
            if os.path.exists(m3u_path):
                try:
                    os.remove(m3u_path)
                    xbmc.log(f"{addon_name}: Deleted M3U file {m3u_path}", level=xbmc.LOGINFO)
                except Exception as e:
                    xbmc.log(f"{addon_name}: Failed to delete M3U file {m3u_path}: {e}", level=xbmc.LOGERROR)
        
        # Clear channels.json
        save_channels([])
        xbmc.log(f"{addon_name}: All channels deleted from channels.json", level=xbmc.LOGINFO)
        dialog.ok(addon_name, "All channels deleted successfully.")
    else:
        # Return to settings dialog (handled by Kodi)
        xbmc.log(f"{addon_name}: Delete all channels cancelled", level=xbmc.LOGINFO)
       

def get_playlist_sort_order(playlist_path):
    """Parse Smart Playlist (.xsp) to determine sort order."""
    try:
        translated_path = xbmcvfs.translatePath(playlist_path)
        xbmc.log(f"{addon_name}: Parsing playlist for sort order: {translated_path}", level=xbmc.LOGDEBUG)
        tree = ET.parse(translated_path)
        root = tree.getroot()
        sort_order = root.find(".//order")
        if sort_order is not None and sort_order.text == "random":
            return "random"
        return "episode"  # Default to episode order
    except Exception as e:
        xbmc.log(f"{addon_name}: Error parsing playlist {playlist_path}: {str(e)}", level=xbmc.LOGERROR)
        return "episode"

def get_episodes_from_playlist(playlist_path):
    """Retrieve episodes from a Smart Playlist by parsing its rules and querying episode metadata."""
    episodes = []
    original_path = playlist_path
    addon_name = "script.smart.channels"  # Match your addon ID
    try:
        # Normalize playlist path
        if playlist_path.startswith("multipath://"):
            decoded_path = urllib.parse.unquote(playlist_path.replace("multipath://", ""))
            paths = decoded_path.split("/")
            playlist_path = next((p for p in paths if p.endswith(".xsp")), None)
            if not playlist_path:
                xbmc.log(f"{addon_name}: No valid .xsp path in multipath {original_path}", level=xbmc.LOGERROR)
                return []
        elif not playlist_path.startswith("special://"):
            for base_path in [
                "special://profile/playlists/video/",
                "special://profile/playlists/mixed/"
            ]:
                test_path = os.path.join(base_path, playlist_path)
                if xbmcvfs.exists(xbmcvfs.translatePath(test_path)):
                    playlist_path = test_path
                    break

        translated_path = xbmcvfs.translatePath(playlist_path)
        xbmc.log(f"{addon_name}: Processing playlist: {translated_path}", level=xbmc.LOGDEBUG)
        if not xbmcvfs.exists(translated_path):
            xbmc.log(f"{addon_name}: Playlist {translated_path} does not exist", level=xbmc.LOGERROR)
            return []
        if not playlist_path.endswith(".xsp"):
            xbmc.log(f"{addon_name}: Playlist {playlist_path} is not a Smart Playlist", level=xbmc.LOGWARNING)
            return []

        # Parse the Smart Playlist XML
        try:
            tree = ET.parse(translated_path)
            root = tree.getroot()
            if root.get("type") != "episodes":
                xbmc.log(f"{addon_name}: Playlist {playlist_path} is not an episode playlist", level=xbmc.LOGWARNING)
                return []
        except Exception as e:
            xbmc.log(f"{addon_name}: Error parsing playlist {translated_path}: {str(e)}", level=xbmc.LOGERROR)
            return []

        # Extract rules
        match_type = root.get("match", "all")
        xbmc.log(f"{addon_name}: Playlist match type: {match_type}", level=xbmc.LOGDEBUG)
        rules = root.findall(".//rule")
        xbmc.log(f"{addon_name}: Found {len(rules)} rules in playlist", level=xbmc.LOGDEBUG)

        # For <match>all</match> with tvshow rules, treat as OR (union of episodes)
        for rule in rules:
            field = rule.get("field")
            operator = rule.get("operator")
            value = rule.find("value").text if rule.find("value") is not None else ""
            xbmc.log(f"{addon_name}: Processing rule: field={field}, operator={operator}, value={value}", level=xbmc.LOGDEBUG)

            if field == "tvshow" and operator == "is":
                # Query episodes for each TV show
                json_query = {
                    "jsonrpc": "2.0",
                    "method": "VideoLibrary.GetEpisodes",
                    "params": {
                        "filter": {"field": "tvshow", "operator": "is", "value": value},
                        "properties": ["showtitle", "season", "episode", "title", "file", "runtime", "tvshowid"]
                    },
                    "id": 2
                }
                result = json.loads(xbmc.executeJSONRPC(json.dumps(json_query)))
                xbmc.log(f"{addon_name}: VideoLibrary.GetEpisodes response for show {value}: {json.dumps(result, indent=2)}", level=xbmc.LOGDEBUG)
                if "result" in result and "episodes" in result["result"]:
                    show_episodes = result["result"]["episodes"]
                    xbmc.log(f"{addon_name}: Found {len(show_episodes)} episodes for show {value}", level=xbmc.LOGINFO)
                    episodes.extend(show_episodes)
                else:
                    xbmc.log(f"{addon_name}: No episodes found for TV show {value}", level=xbmc.LOGWARNING)

        if not episodes:
            xbmc.log(f"{addon_name}: No episodes found in {playlist_path}", level=xbmc.LOGWARNING)
            return []

        xbmc.log(f"{addon_name}: Total episodes found: {len(episodes)}", level=xbmc.LOGINFO)
        
        # Apply sort order
        sort_order = root.find(".//order")
        sort_order = sort_order.text if sort_order is not None else "episode"
        xbmc.log(f"{addon_name}: Applying sort order: {sort_order}", level=xbmc.LOGDEBUG)
        if sort_order == "episode":
            episodes.sort(key=lambda x: (x.get("showtitle", ""), x.get("season", 0), x.get("episode", 0)))
        elif sort_order == "random":
            random.shuffle(episodes)

        return episodes
    except Exception as e:
        xbmc.log(f"{addon_name}: Error querying playlist {original_path}: {str(e)}", level=xbmc.LOGERROR)
        return []

#addon = xbmcaddon.Addon()
#addon_name = addon.getAddonInfo("name")
#data_path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
#settings_file = os.path.join(data_path, "settings.json")  # Define settings_file
#channel_lock = threading.Lock()

def load_settings():
    """Load settings from settings.json. Returns dict with defaults on failure."""
    try:
        if xbmcvfs.exists(settings_file):
            with xbmcvfs.File(settings_file, 'r') as f:
                return json.load(f)
        return {"playlist_upper_limit": 50}
    except Exception as e:
        xbmc.log(f"{addon_name}: Failed to load settings: {str(e)}", level=xbmc.LOGERROR)
        return {"playlist_upper_limit": 50}

def generate_m3u(channel_number, playlist_paths):
    """Generate M3U file with continuous round-robin episodic order, randomizing show order per round and cycling episodes."""
    # Show "Creating Channel" dialog
    progress_dialog = xbmcgui.DialogProgress()
    progress_dialog.create(addon_name, f"Creating Channel {channel_number}, Please wait...")

    settings = load_settings()
    max_entries = int(settings.get("playlist_upper_limit", 50))
    xbmc.log(f"{addon_name}: Loaded max_entries={max_entries} from settings.json", level=xbmc.LOGINFO)

    # Force fresh read of channels.json
    channels = load_channels()
    channel = next((ch for ch in channels if ch["number"] == channel_number), None)
    if not channel:
        xbmc.log(f"{addon_name}: Channel {channel_number} not found in channels.json", level=xbmc.LOGERROR)
        progress_dialog.close()
        xbmcgui.Dialog().ok(addon_name, f"Channel {channel_number} not found.")
        return False
    rules = channel.get("rules", {"randomize_shows": False})
    xbmc.log(f"{addon_name}: Rules for channel {channel_number}: {rules}", level=xbmc.LOGINFO)

    if not playlist_paths:
        xbmc.log(f"{addon_name}: No playlists for channel {channel_number}, skipping M3U generation", level=xbmc.LOGINFO)
        progress_dialog.close()
        xbmcgui.Dialog().ok(addon_name, f"No playlists for Channel {channel_number}.")
        return True

    m3u_content = ["#EXTM3U"]
    all_episodes = []
    skipped_files = []

    # Connect to MyVideos131.db
    db_path = xbmcvfs.translatePath("special://database/MyVideos131.db")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
    except Exception as e:
        xbmc.log(f"{addon_name}: Error connecting to MyVideos131.db: {str(e)}", level=xbmc.LOGERROR)
        progress_dialog.close()
        xbmcgui.Dialog().ok(addon_name, "Failed to connect to database. Check kodi.log.")
        return False

    # Collect episodes from all playlists
    total_playlists = len(playlist_paths)
    for i, playlist_path in enumerate(playlist_paths):
        progress_dialog.update(int(i / total_playlists * 100), f"Processing playlist {i + 1}/{total_playlists}...")
        if not playlist_path.endswith(".xsp"):
            xbmc.log(f"{addon_name}: Skipping non-Smart Playlist {playlist_path}", level=xbmc.LOGWARNING)
            continue
        episodes = get_episodes_from_playlist(playlist_path)
        if episodes:
            shows = []
            for ep in episodes:
                showtitle = ep.get("showtitle", "Unknown")
                file_path = ep.get("file", "")
                duration = 0
                try:
                    cursor.execute("""
                        SELECT iVideoDuration
                        FROM streamdetails
                        WHERE idFile = (
                            SELECT idFile
                            FROM files
                            WHERE strFileName = ? AND idPath = (
                                SELECT idPath
                                FROM path
                                WHERE strPath = ?
                            )
                        )
                    """, (os.path.basename(file_path), os.path.dirname(file_path) + "/"))
                    result = cursor.fetchone()
                    if result and result[0]:
                        duration = result[0]
                        xbmc.log(f"{addon_name}: Found duration {duration}s for {file_path}", level=xbmc.LOGDEBUG)
                    else:
                        duration = 0
                        xbmc.log(f"{addon_name}: No duration found for {file_path}, skipping due to zero duration", level=xbmc.LOGWARNING)
                        skipped_files.append({
                            "channel": str(channel_number),
                            "file_path": file_path,
                            "showtitle": showtitle,
                            "season": ep.get("season", 0),
                            "episode": ep.get("episode", 0),
                            "title": ep.get("title", "Unknown"),
                            "reason": "Zero duration in database",
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        continue
                except Exception as e:
                    xbmc.log(f"{addon_name}: Error querying duration for {file_path}: {str(e)}", level=xbmc.LOGERROR)
                    skipped_files.append({
                        "channel": str(channel_number),
                        "file_path": file_path,
                        "showtitle": showtitle,
                        "season": ep.get("season", 0),
                        "episode": ep.get("episode", 0),
                        "title": ep.get("title", "Unknown"),
                        "reason": "Database query error",
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    continue
                ep["runtime"] = duration
                show_entry = next((s for s in shows if s["showtitle"] == showtitle), None)
                if not show_entry:
                    show_entry = {"showtitle": showtitle, "episodes": []}
                    shows.append(show_entry)
                show_entry["episodes"].append(ep)
            show_titles = [show["showtitle"] for show in shows]
            xbmc.log(f"{addon_name}: Shows before processing for channel {channel_number}: {show_titles}", level=xbmc.LOGINFO)
            all_episodes = shows

    conn.close()

    # Save skipped files
    if skipped_files:
        skipped_file_path = os.path.join(data_path, "skipped_files.json")
        existing_skipped = []
        if xbmcvfs.exists(skipped_file_path):
            try:
                with xbmcvfs.File(skipped_file_path) as file:
                    existing_skipped = json.load(file)
            except Exception as e:
                xbmc.log(f"{addon_name}: Error reading skipped_files.json: {str(e)}", level=xbmc.LOGERROR)
        existing_skipped.extend(skipped_files)
        try:
            with xbmcvfs.File(skipped_file_path, "w") as file:
                json.dump(existing_skipped, file, indent=2)
            xbmc.log(f"{addon_name}: Logged {len(skipped_files)} skipped files to {skipped_file_path}", level=xbmc.LOGINFO)
        except Exception as e:
            xbmc.log(f"{addon_name}: Error writing skipped_files.json: {str(e)}", level=xbmc.LOGERROR)
            progress_dialog.close()
            xbmcgui.Dialog().ok(addon_name, "Failed to log skipped files.")
            return False

    if not all_episodes:
        xbmc.log(f"{addon_name}: No episodes found for channel {channel_number}", level=xbmc.LOGWARNING)
        progress_dialog.close()
        xbmcgui.Dialog().ok(addon_name, "No episodes found in selected playlists.")
        return False

    # Prepare for M3U generation
    m3u_content = ["#EXTM3U"]
    m3u_entries = []
    entry_count = 0
    episode_indices = [0] * len(all_episodes)  # Track episode index per show
    expected_show_orders = []  # Track show order per round for validation
    xbmc.log(f"{addon_name}: Shows before processing for channel {channel_number}: {[show['showtitle'] for show in all_episodes]}", level=xbmc.LOGINFO)

    # Round-robin through shows, randomizing order each round
    round_num = 0
    while entry_count < max_entries:
        round_num += 1
        # Use all shows, as episodes will cycle
        round_shows = all_episodes.copy()
        if not round_shows:
            xbmc.log(f"{addon_name}: No shows available for channel {channel_number}, stopping at {entry_count} entries", level=xbmc.LOGINFO)
            break

        if rules["randomize_shows"]:
            try:
                random.seed(42 + entry_count)  # Unique seed per round for testing
                random.shuffle(round_shows)
                round_order = [show["showtitle"] for show in round_shows]
                xbmc.log(f"{addon_name}: Round {round_num} show order for channel {channel_number}: {round_order}", level=xbmc.LOGINFO)
                expected_show_orders.append(round_order)
            except Exception as e:
                xbmc.log(f"{addon_name}: Error shuffling shows for round {round_num}: {str(e)}", level=xbmc.LOGERROR)
                progress_dialog.close()
                xbmcgui.Dialog().ok(addon_name, "Failed to shuffle shows. Check kodi.log.")
                return False
        else:
            round_shows.sort(key=lambda x: x["showtitle"])
            round_order = [show["showtitle"] for show in round_shows]
            xbmc.log(f"{addon_name}: Round {round_num} sorted show order for channel {channel_number}: {round_order}", level=xbmc.LOGINFO)
            expected_show_orders.append(round_order)

        # Process one episode from each show in this round's order
        for i, show in enumerate(round_shows):
            progress_dialog.update(int((entry_count + i) / max_entries * 100), f"Building M3U: Round {round_num}, Show {i + 1}/{len(round_shows)}")
            show_idx = next(i for i, s in enumerate(all_episodes) if s["showtitle"] == show["showtitle"])
            episodes = show["episodes"]
            if not episodes:  # Skip empty shows
                continue
            # Cycle episode index using modulo
            episode_idx = episode_indices[show_idx] % len(episodes)
            episode = episodes[episode_idx]
            showtitle = show["showtitle"]
            season = episode.get("season", 0)
            episode_num = episode.get("episode", 0)
            title = episode.get("title", "Unknown")
            filepath = episode.get("file", "")
            duration = episode.get("runtime", 0)
            m3u_entries.append(f"#EXTINF:{duration},{showtitle} S{season:02d}E{episode_num:02d} - {title}")
            m3u_entries.append(filepath)
            xbmc.log(f"{addon_name}: Added to M3U: {showtitle} S{season:02d}E{episode_num:02d} - {title} (duration: {duration}s)", level=xbmc.LOGDEBUG)
            episode_indices[show_idx] += 1
            entry_count += 1
            if entry_count >= max_entries:
                xbmc.log(f"{addon_name}: Reached max_entries {max_entries} for channel {channel_number}", level=xbmc.LOGINFO)
                break
        if entry_count >= max_entries:
            break

    m3u_content.extend(m3u_entries)

    # Verify M3U order
    actual_order = []
    for line in m3u_content[1::2]:
        for show in all_episodes:
            if show["showtitle"] in line:
                actual_order.append(show["showtitle"])
                break
    xbmc.log(f"{addon_name}: Actual M3U show order for channel {channel_number}: {actual_order}", level=xbmc.LOGINFO)

    # Validate show order per round
    entries_per_round = len(all_episodes)
    for round_idx in range(len(expected_show_orders)):
        start = round_idx * entries_per_round
        end = min((round_idx + 1) * entries_per_round, len(actual_order))
        round_actual = actual_order[start:end]
        round_expected = expected_show_orders[round_idx][:len(round_actual)]
        if round_actual != round_expected:
            xbmc.log(f"{addon_name}: M3U order mismatch in round {round_idx + 1}! Expected: {round_expected}, Got: {round_actual}", level=xbmc.LOGERROR)

    if not m3u_entries:
        xbmc.log(f"{addon_name}: No entries added to M3U for channel {channel_number}", level=xbmc.LOGWARNING)
        progress_dialog.close()
        xbmcgui.Dialog().ok(addon_name, "No entries added to M3U file.")
        return False

    # Write M3U file
    m3u_path = os.path.join(data_path, f"channel_{channel_number}.m3u")
    xbmc.log(f"{addon_name}: Attempting to write M3U file to {m3u_path}", level=xbmc.LOGINFO)
    try:
        # Ensure directory exists
        m3u_dir = os.path.dirname(m3u_path)
        if not xbmcvfs.exists(m3u_dir):
            xbmcvfs.mkdirs(m3u_dir)
            xbmc.log(f"{addon_name}: Created directory {m3u_dir}", level=xbmc.LOGINFO)

        # Delete existing file
        if xbmcvfs.exists(m3u_path):
            try:
                xbmcvfs.delete(m3u_path)
                xbmc.log(f"{addon_name}: Deleted existing M3U file {m3u_path}", level=xbmc.LOGINFO)
            except Exception as e:
                xbmc.log(f"{addon_name}: Error deleting existing M3U file {m3u_path}: {str(e)}", level=xbmc.LOGERROR)
                progress_dialog.close()
                xbmcgui.Dialog().ok(addon_name, f"Failed to delete existing M3U file. Check kodi.log.")
                return False

        # Try writing with xbmcvfs
        try:
            with xbmcvfs.File(m3u_path, "w") as file:
                file.write("\n".join(m3u_content))
            xbmc.log(f"{addon_name}: Successfully wrote M3U file using xbmcvfs to {m3u_path} with {len(m3u_entries) // 2} entries", level=xbmc.LOGINFO)
        except Exception as e:
            xbmc.log(f"{addon_name}: xbmcvfs write failed for {m3u_path}: {str(e)}", level=xbmc.LOGERROR)
            # Fallback to standard Python I/O
            try:
                real_path = xbmcvfs.translatePath(m3u_path)
                with open(real_path, "w", encoding="utf-8") as file:
                    file.write("\n".join(m3u_content))
                xbmc.log(f"{addon_name}: Successfully wrote M3U file using Python I/O to {real_path} with {len(m3u_entries) // 2} entries", level=xbmc.LOGINFO)
            except Exception as e:
                xbmc.log(f"{addon_name}: Python I/O write failed for {real_path}: {str(e)}", level=xbmc.LOGERROR)
                progress_dialog.close()
                xbmcgui.Dialog().ok(addon_name, f"Failed to create M3U file at {m3u_path}. Check kodi.log.")
                return False

        # Verify file exists
        if xbmcvfs.exists(m3u_path):
            xbmc.log(f"{addon_name}: Confirmed M3U file exists at {m3u_path}", level=xbmc.LOGINFO)
            progress_dialog.close()
            xbmcgui.Dialog().ok(addon_name, f"Channel {channel_number} Creation Success")
            return True
        else:
            xbmc.log(f"{addon_name}: M3U file not found at {m3u_path} after writing", level=xbmc.LOGERROR)
            progress_dialog.close()
            xbmcgui.Dialog().ok(addon_name, f"M3U file not created at {m3u_path}. Check kodi.log.")
            return False

    except Exception as e:
        xbmc.log(f"{addon_name}: General error writing M3U file {m3u_path}: {str(e)}", level=xbmc.LOGERROR)
        progress_dialog.close()
        xbmcgui.Dialog().ok(addon_name, f"Failed to create M3U file. Check kodi.log.")
        return False

def validate_channel_number(number, channels, exclude_index=None):
    """Check if channel number is unique, excluding the channel at exclude_index (for edits)."""
    if not number.isdigit():
        xbmcgui.Dialog().ok(addon_name, "Channel number must be a valid number.")
        return False
    for i, ch in enumerate(channels):
        if i != exclude_index and ch['number'] == number:
            xbmcgui.Dialog().ok(addon_name, addon.getLocalizedString(32016))  # Channel number already exists
            return False
    return True

def show_existing_channels():
    """Display a dialog with existing channels from channels.json."""
    dialog = xbmcgui.Dialog()
    channels = load_channels()
    if not channels:
        dialog.ok(addon_name, addon.getLocalizedString(32019))  # No channels to display
        return
    # Format channel details for display
    channel_details = [
        f"Channel {ch['number']}: {ch['name']} ({len(ch['playlists'])} playlists)"
        for ch in channels
    ]
    dialog.textviewer(addon.getLocalizedString(32024), "\n".join(channel_details))

def configure_advanced_rules(channel_index=None):
    """Configure advanced channel rules using a dialog, extensible for future rules."""
    dialog = xbmcgui.Dialog()
    channels = load_channels()
    
    if channel_index is None or channel_index >= len(channels):
        dialog.ok(addon_name, "No channel selected for advanced rules.")
        return
    
    channel = channels[channel_index]
    # Ensure rules dictionary exists
    if "rules" not in channel:
        channel["rules"] = {"randomize_shows": False}
    
    # Remove legacy top-level randomize_shows key if present
    if "randomize_shows" in channel:
        del channel["randomize_shows"]
        xbmc.log(f"{addon_name}: Removed legacy randomize_shows key for channel {channel['number']}", level=xbmc.LOGINFO)

    # Define available rules
    rule_options = [
        f"{'Disable' if channel['rules'].get('randomize_shows', False) else 'Enable'} Randomize TV Shows (episodes in order)"
        # Add future rules here
    ]
    choice = dialog.select(f"Advanced Rules for Channel {channel['number']}: {channel['name']}", rule_options)
    
    if choice == -1:
        return
    
    if choice == 0:  # Randomize TV Shows
        channel["rules"]["randomize_shows"] = not channel["rules"].get("randomize_shows", False)
        xbmc.log(f"{addon_name}: Set randomize_shows to {channel['rules']['randomize_shows']} for channel {channel['number']}", level=xbmc.LOGINFO)
        dialog.ok(addon_name, f"Randomize TV Shows {'enabled' if channel['rules']['randomize_shows'] else 'disabled'} for channel {channel['number']}.")
    
    # Save updated channels
    save_channels(channels)

def select_playlists():
    """Display a dialog to select Smart Playlists and return their paths."""
    addon_name = "script.smart.channels"
    playlist_dirs = [
        "special://profile/playlists/video/",
        "special://profile/playlists/mixed/"
    ]
    playlists = []
    
    # Collect all .xsp files from playlist directories
    for dir_path in playlist_dirs:
        translated_dir = xbmcvfs.translatePath(dir_path)
        if xbmcvfs.exists(translated_dir):
            dirs, files = xbmcvfs.listdir(translated_dir)
            for file in files:
                if file.endswith(".xsp"):
                    playlists.append(os.path.join(dir_path, file))
    
    if not playlists:
        xbmc.log(f"{addon_name}: No .xsp playlists found in {playlist_dirs}", level=xbmc.LOGWARNING)
        xbmcgui.Dialog().ok(addon_name, "No Smart Playlists found.")
        return []

    # Display multi-select dialog
    playlist_names = [os.path.basename(p) for p in playlists]
    selected = xbmcgui.Dialog().multiselect("Select Playlists for Channel", playlist_names)
    if selected is None or not selected:
        xbmc.log(f"{addon_name}: No playlists selected", level=xbmc.LOGINFO)
        return []
    
    selected_playlists = [playlists[i] for i in selected]
    xbmc.log(f"{addon_name}: Selected playlists: {selected_playlists}", level=xbmc.LOGDEBUG)
    return selected_playlists

def add_channel():
    """Dialog to add a new channel with validation and empty channel support."""
    dialog = xbmcgui.Dialog()
    channels = load_channels()

    # Show existing channels before adding a new one
    show_existing_channels()

    # Input Channel Number
    while True:
        channel_number = dialog.input("Enter Channel Number", type=xbmcgui.INPUT_NUMERIC)
        if not channel_number:
            # Assign next available channel number
            existing_numbers = [int(ch['number']) for ch in channels if ch['number'].isdigit()]
            channel_number = str(max(existing_numbers, default=0) + 1)
        if validate_channel_number(channel_number, channels):
            break

    # Input Channel Name
    channel_name = dialog.input("Enter Channel Name", type=xbmcgui.INPUT_ALPHANUM)
    if not channel_name:
        channel_name = "Empty Channel"

    # Select Playlists
    playlists = select_playlists()
    if not playlists:
        create_empty = dialog.yesno(addon_name, addon.getLocalizedString(32015))  # Create Empty Channel?
        if not create_empty:
            return None
        playlists = []

    # Create channel data with rules dictionary
    channel_data = {
        "number": channel_number,
        "name": channel_name,
        "playlists": playlists,
        "rules": {"randomize_shows": False}  # Initialize rules
    }

    # Save the channel before configuring rules
    channels.append(channel_data)
    save_channels(channels)
    dialog.ok(addon_name, f"Channel {channel_data['name']} added successfully!")

    # Configure advanced rules
    configure_rules = dialog.yesno(addon_name, addon.getLocalizedString(32021))  # Configure Advanced Channel Rules?
    if configure_rules:
        configure_advanced_rules(len(channels) - 1)

    # Generate M3U file
    if playlists:
        if not generate_m3u(channel_number, playlists):
            dialog.ok(addon_name, "Channel created, but M3U file generation failed.")
    
    return channel_data

def edit_channel_number_name(channels, channel_index):
    """Edit channel number and name with validation."""
    dialog = xbmcgui.Dialog()
    current_channel = channels[channel_index]

    # Input new Channel Number
    while True:
        new_number = dialog.input("Edit Channel Number", defaultt=current_channel['number'], type=xbmcgui.INPUT_NUMERIC)
        if not new_number:
            new_number = current_channel['number']  # Keep existing if empty
        if validate_channel_number(new_number, channels, exclude_index=channel_index):
            break
        # Continue loop if number is invalid or duplicate

    # Input new Channel Name
    new_name = dialog.input("Edit Channel Name", defaultt=current_channel['name'], type=xbmcgui.INPUT_ALPHANUM)
    if not new_name:
        new_name = "Empty Channel"

    # Update channel
    channels[channel_index]['number'] = new_number
    channels[channel_index]['name'] = new_name
    save_channels(channels)
    dialog.ok(addon_name, addon.getLocalizedString(32018))  # Channel updated successfully

def display_channels():
    """Display a list of channels with their details."""
    dialog = xbmcgui.Dialog()
    channels = load_channels()
    if not channels:
        dialog.ok(addon_name, addon.getLocalizedString(32019))  # No channels to display
        return

    # Create a formatted list of channel details
    channel_details = [
        f"Channel {ch['number']}: {ch['name']} ({len(ch['playlists'])} playlists)"
        for ch in channels
    ]
    dialog.textviewer(addon_name, "\n".join(channel_details))

def manage_channels():
    """Show Add/Edit dialog and handle user selection."""
    dialog = xbmcgui.Dialog()
    options = ["Add", "Edit"]
    choice = dialog.select("Manage Channels", options)

    if choice == -1:
        return

    if choice == 0:  # Add
        channel_data = add_channel()
        if not channel_data:
            dialog.ok(addon_name, addon.getLocalizedString(32014))  # Channel creation cancelled

    elif choice == 1:  # Edit
        channels = load_channels()
        if not channels:
            dialog.ok(addon_name, addon.getLocalizedString(32007))  # No Channels Created
            return

        channel_names = [f"{ch['number']}: {ch['name']}" for ch in channels]
        channel_index = dialog.select("Select Channel to Edit", channel_names)
        if channel_index == -1:
            return

        edit_options = ["Edit Channel Number/Name", "Delete Channel", "Delete Playlist", "Add Playlist", "Configure Advanced Rules"]
        edit_choice = dialog.select(f"Edit Channel: {channels[channel_index]['name']}", edit_options)
        if edit_choice == -1:
            return

        if edit_choice == 0:  # Edit Channel Number/Name
            edit_channel_number_name(channels, channel_index)
        elif edit_choice == 1:  # Delete Channel
            channel_number = channels[channel_index]["number"]
            channels.pop(channel_index)
            save_channels(channels)
            m3u_path = os.path.join(data_path, f"channel_{channel_number}.m3u")
            if xbmcvfs.exists(m3u_path):
                try:
                    xbmcvfs.delete(m3u_path)
                    xbmc.log(f"{addon_name}: Successfully deleted M3U file for channel {channel_number}", level=xbmc.LOGINFO)
                except Exception as e:
                    xbmc.log(f"{addon_name}: Error deleting M3U file {m3u_path}: {str(e)}", level=xbmc.LOGERROR)
            dialog.ok(addon_name, addon.getLocalizedString(32008))  # Channel deleted successfully
        elif edit_choice == 2:  # Delete Playlist
            playlists = channels[channel_index]["playlists"]
            if not playlists:
                dialog.ok(addon_name, addon.getLocalizedString(32009))  # No playlists available
                return
            playlist_names = [os.path.basename(p) for p in playlists]
            selected = dialog.multiselect("Select Playlists to Delete", playlist_names)
            if selected is None or not selected:
                return
            channels[channel_index]["playlists"] = [
                p for i, p in enumerate(playlists) if i not in selected
            ]
            if not channels[channel_index]["playlists"]:
                dialog.ok(addon_name, addon.getLocalizedString(32011))  # Channel Empty
            save_channels(channels)
            dialog.ok(addon_name, addon.getLocalizedString(32010))  # Playlists deleted successfully
        elif edit_choice == 3:  # Add Playlist
            new_playlists = select_playlists()
            if new_playlists:
                settings = load_settings()
                playlist_limit = int(addon.getSetting('playlist_upper_limit') or settings.get('playlist_upper_limit', 50))
                current_playlists = len(channels[channel_index]["playlists"])
                if current_playlists + len(new_playlists) > playlist_limit:
                    dialog.ok(addon_name, f"Cannot add playlists. Total would exceed limit of {playlist_limit}.")
                    return
                channels[channel_index]["playlists"].extend(new_playlists)
                save_channels(channels)
                dialog.ok(addon_name, addon.getLocalizedString(32012))  # Playlists added successfully
        elif edit_choice == 4:  # Configure Advanced Rules
            configure_advanced_rules(channel_index)
            
 
def update_settings():
    """Update settings.json with the current addon settings."""
    settings = load_settings()
    settings['playlist_upper_limit'] = int(addon.getSetting('playlist_upper_limit') or 50)
    save_settings(settings)

class SettingsMonitor(xbmc.Monitor):
    """Monitor for settings changes to update settings.json."""
    def __init__(self):
        super(SettingsMonitor, self).__init__()

    def onSettingsChanged(self):
        xbmc.log(f"{addon_name}: Settings changed, updating settings.json", level=xbmc.LOGINFO)
        update_settings()

def main():
    """Main entry point for the addon."""
    global addon_name
    addon = xbmcaddon.Addon()
    addon_name = addon.getAddonInfo('name')
    dialog = xbmcgui.Dialog()

    # Initialize settings monitor
    monitor = SettingsMonitor()

    # Update settings.json with current addon settings
    update_settings()

    if len(sys.argv) > 1:
        action = sys.argv[1]
        if action == "manage_channels":
            manage_channels()
        elif action == "delete_all_channels":
            delete_all_channels()
        else:
            xbmc.log(f"{addon_name}: Unknown action {action}", level=xbmc.LOGERROR)
            # Fallback to main menu
            options = [addon.getLocalizedString(32020)]  # View Channels
            choice = dialog.select(addon_name, options)
            if choice == -1:
                return  # Cancelled
            if choice == 0:  # View Channels
                display_channels()
    else:
        # Show main menu with options
        options = [addon.getLocalizedString(32020)]  # View Channels
        choice = dialog.select(addon_name, options)
        if choice == -1:
            return  # Cancelled
        if choice == 0:  # View Channels
            display_channels()

if __name__ == "__main__":
    main()