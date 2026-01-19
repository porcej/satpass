"""TLE fetching from different sources (AMSAT, CelesTrak, Space-Track)"""

import requests
from typing import Dict, Tuple, List, Optional
from .config import get_spacetrack_credentials


def fetch_amsat(satellite_ids: List[str]) -> Dict[str, Tuple[str, str, str]]:
    """
    Fetch TLEs from AMSAT.
    
    Args:
        satellite_ids: List of satellite names or NORAD IDs
    
    Returns:
        Dictionary mapping satellite identifier to (name, line1, line2) tuple
    """
    # AMSAT TLE URL
    url = 'https://amsat.org/tle/current/nasabare.txt'
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return _parse_tle_text(response.text, satellite_ids)
    except Exception as e:
        raise Exception(f"Failed to fetch TLEs from AMSAT: {e}")


def fetch_celestrak(satellite_ids: List[str]) -> Dict[str, Tuple[str, str, str]]:
    """
    Fetch TLEs from CelesTrak.
    
    Args:
        satellite_ids: List of satellite names or NORAD IDs
    
    Returns:
        Dictionary mapping satellite identifier to (name, line1, line2) tuple
    """
    # Try active satellites first
    urls = [
        'https://celestrak.org/NORAD/elements/active.txt',
        'https://celestrak.org/NORAD/elements/stations.txt',  # ISS and other stations
        'https://celestrak.org/NORAD/elements/weather.txt',   # Weather satellites
        'https://celestrak.org/NORAD/elements/noaa.txt',     # NOAA satellites
    ]
    
    all_tles = {}
    for url in urls:
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            tles = _parse_tle_text(response.text, satellite_ids)
            all_tles.update(tles)
            # If we found all requested satellites, we can stop
            if len(all_tles) >= len(satellite_ids):
                break
        except Exception:
            continue
    
    if not all_tles:
        raise Exception("Failed to fetch TLEs from CelesTrak")
    
    return all_tles


def fetch_spacetrack(satellite_ids: List[str], config_path: Optional[str] = None) -> Dict[str, Tuple[str, str, str]]:
    """
    Fetch TLEs from Space-Track API.
    
    Args:
        satellite_ids: List of satellite names or NORAD IDs
        config_path: Optional path to config.ini file
    
    Returns:
        Dictionary mapping satellite identifier to (name, line1, line2) tuple
    """
    username, password = get_spacetrack_credentials(config_path)
    
    if not username or not password:
        raise Exception("Space-Track credentials not found. Please configure config.ini with username and password.")
    
    # Space-Track API requires authentication
    # First, login to get a cookie
    login_url = 'https://www.space-track.org/ajaxauth/login'
    login_data = {
        'identity': username,
        'password': password
    }
    
    session = requests.Session()
    try:
        # Login
        response = session.post(login_url, data=login_data, timeout=10)
        response.raise_for_status()
        
        # Extract NORAD IDs from satellite_ids (they might be names or IDs)
        norad_ids = []
        for sat_id in satellite_ids:
            try:
                # If it's already a number, use it
                norad_id = int(sat_id)
                norad_ids.append(norad_id)
            except ValueError:
                # If it's a name, we'll need to search for it
                # For now, try to extract from the list
                pass
        
        if not norad_ids:
            # Try to get TLEs by name - this is more complex with Space-Track
            # For simplicity, we'll try to fetch all and filter
            query_url = 'https://www.space-track.org/basicspacedata/query/class/tle_latest/ORDINAL/1/format/tle'
            response = session.get(query_url, timeout=10)
            response.raise_for_status()
            return _parse_tle_text(response.text, satellite_ids)
        else:
            # Fetch specific NORAD IDs
            norad_str = ','.join(map(str, norad_ids))
            query_url = f'https://www.space-track.org/basicspacedata/query/class/tle_latest/NORAD_CAT_ID/{norad_str}/format/tle'
            response = session.get(query_url, timeout=10)
            response.raise_for_status()
            return _parse_tle_text(response.text, satellite_ids)
            
    except Exception as e:
        raise Exception(f"Failed to fetch TLEs from Space-Track: {e}")
    finally:
        session.close()


def _parse_tle_text(text: str, satellite_ids: List[str]) -> Dict[str, Tuple[str, str, str]]:
    """
    Parse TLE text and extract TLEs for requested satellites.
    
    Args:
        text: TLE file content as string
        satellite_ids: List of satellite names or NORAD IDs to find
    
    Returns:
        Dictionary mapping satellite identifier to (name, line1, line2) tuple
    """
    lines = text.strip().split('\n')
    tles = {}
    i = 0
    
    # Normalize satellite_ids for matching (case-insensitive, strip whitespace)
    normalized_ids = {sat_id.strip().upper() for sat_id in satellite_ids}
    
    while i < len(lines) - 2:
        name_line = lines[i].strip()
        line1 = lines[i + 1].strip() if i + 1 < len(lines) else ""
        line2 = lines[i + 2].strip() if i + 2 < len(lines) else ""
        
        # Check if this is a valid TLE (name line, then line1 starting with '1 ', then line2 starting with '2 ')
        if line1.startswith('1 ') and line2.startswith('2 '):
            # Extract NORAD ID from line1 (second field)
            try:
                parts = line1.split()
                if len(parts) >= 2:
                    norad_id_full = parts[1]  # e.g., "25544U"
                    # Extract numeric part (strip any trailing letters like 'U', 'S', etc.)
                    norad_id = ''.join(c for c in norad_id_full if c.isdigit())
                    
                    # Check if this satellite matches any requested ID
                    # Match by NORAD ID or by name
                    name_upper = name_line.upper()
                    matched_id = None
                    
                    for sat_id in satellite_ids:
                        sat_id_upper = sat_id.strip().upper()
                        # Match by NORAD ID (exact match on full ID)
                        if sat_id_upper == norad_id_full.upper():
                            matched_id = sat_id
                            break
                        # Match by numeric NORAD ID
                        try:
                            if int(sat_id.strip()) == int(norad_id):
                                matched_id = sat_id
                                break
                        except (ValueError, TypeError):
                            pass
                        # Match by name (partial match)
                        if sat_id_upper in name_upper or name_upper in sat_id_upper:
                            matched_id = sat_id
                            break
                    
                    if matched_id:
                        tles[matched_id] = (name_line, line1, line2)
                    # Skip the next two lines since we've processed this TLE
                    i += 3
                    continue
            except (ValueError, IndexError):
                pass
        
        i += 1
    
    return tles


def fetch_tles(source: str, satellite_ids: List[str], config_path: Optional[str] = None) -> Dict[str, Tuple[str, str, str]]:
    """
    Unified interface to fetch TLEs from different sources.
    
    Args:
        source: Source name ('amsat', 'celestrak', or 'spacetrack')
        satellite_ids: List of satellite names or NORAD IDs
        config_path: Optional path to config.ini file (for Space-Track)
    
    Returns:
        Dictionary mapping satellite identifier to (name, line1, line2) tuple
    """
    source_lower = source.lower()
    
    if source_lower == 'amsat':
        return fetch_amsat(satellite_ids)
    elif source_lower == 'celestrak':
        return fetch_celestrak(satellite_ids)
    elif source_lower == 'spacetrack':
        return fetch_spacetrack(satellite_ids, config_path)
    else:
        raise ValueError(f"Unknown TLE source: {source}")
