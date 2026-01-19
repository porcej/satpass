#!/usr/bin/env python3
"""Main entry point for satellite pass prediction application"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from dateutil import parser as date_parser
from dateutil import tz as dateutil_tz
from typing import List, Dict
from tabulate import tabulate

from .tle_fetcher import fetch_tles
from .pass_predictor import create_predictor, compute_passes, PassInfo
from .eclipse import is_in_eclipse, check_eclipse_during_pass
from .config import get_spacetrack_credentials
from orbit_predictor.locations import Location


def parse_datetime(datetime_str: str) -> datetime:
    """
    Parse datetime string in various formats.
    
    Args:
        datetime_str: Datetime string (ISO format or common formats)
    
    Returns:
        datetime object (UTC)
    """
    try:
        dt = date_parser.parse(datetime_str)
        # Ensure timezone-aware, convert to UTC
        if dt.tzinfo is None:
            # Assume UTC if no timezone specified
            dt = dt.replace(tzinfo=dateutil_tz.UTC)
        else:
            dt = dt.astimezone(dateutil_tz.UTC)
        # Remove timezone info for naive datetime (orbit-predictor expects naive UTC)
        return dt.replace(tzinfo=None)
    except Exception as e:
        raise ValueError(f"Invalid datetime format: {datetime_str}. Error: {e}")


def get_sun_position(time: datetime):
    """
    Get Sun position at given time.
    Simplified version - for production, use a proper ephemeris library.
    
    Args:
        time: datetime object
    
    Returns:
        (x, y, z) position of Sun in ECI frame (km)
    """
    # This is a placeholder - in production, use skyfield or similar
    # For now, return approximate position
    # The actual implementation should use a proper ephemeris
    import math
    
    # Simplified: approximate Sun position (not accurate, but functional)
    # In production, use skyfield or jplephem
    days_since_epoch = (time - datetime(2000, 1, 1)).days
    # Approximate mean anomaly (very simplified)
    mean_anomaly = 2 * math.pi * days_since_epoch / 365.25
    # Earth-Sun distance approximately 149.6 million km
    sun_distance_km = 149600000.0
    # Simplified position (this should use proper ephemeris)
    x = sun_distance_km * math.cos(mean_anomaly)
    y = sun_distance_km * math.sin(mean_anomaly)
    z = 0.0
    
    return (x, y, z)


def get_satellite_position(predictor, time: datetime):
    """
    Get satellite position at given time.
    
    Args:
        predictor: TLEPredictor instance
        time: datetime object
    
    Returns:
        (x, y, z) position of satellite in ECI frame (km)
    """
    position = predictor.get_position(time)
    return position.position_km


def check_pass_eclipse(pass_info: PassInfo, predictor) -> bool:
    """
    Check if satellite is in eclipse during the pass.
    
    Args:
        pass_info: PassInfo object
        predictor: TLEPredictor instance
    
    Returns:
        True if satellite is in eclipse at any point during the pass
    """
    # Sample times during the pass
    duration = (pass_info.set_time - pass_info.rise_time).total_seconds()
    num_samples = max(5, int(duration / 60))  # Sample every minute, minimum 5 samples
    
    sample_times = []
    for i in range(num_samples):
        sample_time = pass_info.rise_time + timedelta(seconds=duration * i / (num_samples - 1))
        sample_times.append(sample_time)
    
    # Check eclipse at each sample time
    for time in sample_times:
        try:
            sat_pos = get_satellite_position(predictor, time)
            sun_pos = get_sun_position(time)
            if is_in_eclipse(sat_pos, sun_pos):
                return True
        except Exception:
            continue
    
    return False


def format_pass_table(passes: List[Dict]) -> str:
    """
    Format pass data as a table.
    
    Args:
        passes: List of dictionaries with pass information
    
    Returns:
        Formatted table string
    """
    if not passes:
        return "No passes found in the specified time window."
    
    headers = ["Rise Time (UTC)", "Peak Time (UTC)", "Set Time (UTC)", 
               "Max Elevation (°)", "Satellite Name/ID", "Eclipse"]
    
    rows = []
    for p in passes:
        rows.append([
            p['rise_time'].strftime('%Y-%m-%d %H:%M:%S'),
            p['peak_time'].strftime('%Y-%m-%d %H:%M:%S'),
            p['set_time'].strftime('%Y-%m-%d %H:%M:%S'),
            f"{p['max_elevation']:.1f}",
            f"{p['satellite_name']} ({p['satellite_id']})",
            "Yes" if p['eclipse'] else "No"
        ])
    
    return tabulate(rows, headers=headers, tablefmt="grid")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Predict satellite passes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Predict passes for ISS using AMSAT (default source)
  python -m satpass.main --satellites 25544 --lat 40.7128 --lon -74.0060
  
  # Predict passes for multiple satellites using CelesTrak
  python -m satpass.main --source celestrak --satellites 25544 25338 --lat 40.7128 --lon -74.0060 --duration 24
  
  # Predict passes starting at a specific time
  python -m satpass.main --satellites 25544 --lat 40.7128 --lon -74.0060 --start "2024-01-01 12:00:00" --duration 6
        """
    )
    
    parser.add_argument(
        '--source',
        choices=['amsat', 'celestrak', 'spacetrack'],
        default='amsat',
        help='TLE source (default: amsat)'
    )
    
    parser.add_argument(
        '--start',
        type=str,
        default=None,
        help='Start datetime in ISO format or common formats (default: now UTC)'
    )
    
    parser.add_argument(
        '--duration',
        type=float,
        default=1.0,
        help='Duration in hours (default: 1.0)'
    )
    
    parser.add_argument(
        '--satellites',
        type=str,
        nargs='+',
        required=True,
        help='List of satellite names or NORAD IDs'
    )
    
    parser.add_argument(
        '--lat',
        type=float,
        required=True,
        help='Observer latitude in degrees (required)'
    )
    
    parser.add_argument(
        '--lon',
        type=float,
        required=True,
        help='Observer longitude in degrees (required)'
    )
    
    parser.add_argument(
        '--elevation',
        type=float,
        default=0.0,
        help='Observer elevation in meters (default: 0)'
    )
    
    parser.add_argument(
        '--min-elevation',
        type=float,
        default=0.0,
        dest='min_elevation',
        help='Minimum elevation in degrees to consider a pass (default: 0.0, orbit-predictor default is 5.0)'
    )
    
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Path to config.ini file for Space-Track credentials (optional)'
    )
    
    args = parser.parse_args()
    
    # Parse start time
    if args.start:
        try:
            start_time = parse_datetime(args.start)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        start_time = datetime.now(timezone.utc).replace(tzinfo=None)
    
    end_time = start_time + timedelta(hours=args.duration)
    
    # Create observer location
    try:
        location = Location("Observer", args.lat, args.lon, args.elevation)
    except Exception as e:
        print(f"Error creating observer location: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Fetch TLEs
    print(f"Fetching TLEs from {args.source}...", file=sys.stderr)
    try:
        tles = fetch_tles(args.source, args.satellites, args.config)
    except Exception as e:
        print(f"Error fetching TLEs: {e}", file=sys.stderr)
        sys.exit(1)
    
    if not tles:
        print("Error: No TLE data found for specified satellites.", file=sys.stderr)
        sys.exit(1)
    
    print(f"Found TLEs for {len(tles)} satellite(s)", file=sys.stderr)
    
    # Compute passes for each satellite
    all_passes = []
    
    for sat_id, (name, line1, line2) in tles.items():
        print(f"Computing passes for {name} ({sat_id})...", file=sys.stderr)
        
        try:
            # Extract NORAD ID from TLE line1 (remove any suffix like 'U')
            try:
                norad_id_full = line1.split()[1]
                # Extract just the numeric part
                norad_id = ''.join(c for c in norad_id_full if c.isdigit())
            except (IndexError, ValueError):
                norad_id = sat_id
            
            # Create predictor
            predictor = create_predictor(name, line1, line2)
            
            # Compute passes
            passes = compute_passes(predictor, location, start_time, end_time, 
                                  satellite_name=name, satellite_id=norad_id,
                                  min_elevation_deg=args.min_elevation)
            
            # Check eclipse for each pass
            for pass_info in passes:
                eclipse = check_pass_eclipse(pass_info, predictor)
                
                all_passes.append({
                    'rise_time': pass_info.rise_time,
                    'peak_time': pass_info.peak_time,
                    'set_time': pass_info.set_time,
                    'max_elevation': pass_info.max_elevation,
                    'satellite_name': pass_info.satellite_name,
                    'satellite_id': pass_info.satellite_id,
                    'eclipse': eclipse
                })
                
        except Exception as e:
            print(f"Warning: Error computing passes for {sat_id}: {e}", file=sys.stderr)
            continue
    
    # Sort by peak time in descending order (latest first)
    all_passes.sort(key=lambda x: x['peak_time'], reverse=True)
    
    # Display results
    print(format_pass_table(all_passes))


if __name__ == '__main__':
    main()
