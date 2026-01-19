"""Pass prediction logic using orbit propagation"""

from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from orbit_predictor.sources import get_predictor_from_tle_lines
from orbit_predictor.locations import Location


class PassInfo:
    """Information about a satellite pass"""
    
    def __init__(self, rise_time: datetime, peak_time: datetime, set_time: datetime,
                 max_elevation: float, satellite_name: str, satellite_id: str):
        self.rise_time = rise_time
        self.peak_time = peak_time
        self.set_time = set_time
        self.max_elevation = max_elevation
        self.satellite_name = satellite_name
        self.satellite_id = satellite_id


def create_predictor(name: str, line1: str, line2: str):
    """
    Create a TLE predictor from TLE lines.
    
    Args:
        name: Satellite name
        line1: First line of TLE
        line2: Second line of TLE
    
    Returns:
        Predictor instance
    """
    return get_predictor_from_tle_lines((line1, line2))


def compute_passes(predictor,
                   location: Location,
                   start_time: datetime,
                   end_time: datetime,
                   satellite_name: str = "Unknown",
                   satellite_id: str = "Unknown",
                   min_elevation_deg: float = 0.0) -> List[PassInfo]:
    """
    Compute all satellite passes for a given location and time window.
    
    Args:
        predictor: TLEPredictor instance
        location: Observer location
        start_time: Start of time window
        end_time: End of time window
        min_elevation_deg: Minimum elevation threshold (default 0.0)
    
    Returns:
        List of PassInfo objects
    """
    passes = []
    current_time = start_time
    
    # orbit-predictor API: get_next_pass returns one pass at a time
    # We need to iterate until we exceed end_time
    while current_time < end_time:
        try:
            # Get the next pass after current_time
            # API: get_next_pass(location, when_utc=None, max_elevation_gt=5, aos_at_dg=0, limit_date=None, ...)
            pass_data = predictor.get_next_pass(
                location,
                when_utc=current_time,
                max_elevation_gt=min_elevation_deg,
                limit_date=end_time
            )
            
            # Check if pass is within our time window
            if pass_data.aos > end_time:
                break
            
            if pass_data.aos < start_time:
                # Skip passes that start before our window
                current_time = pass_data.los + timedelta(seconds=1)
                continue
            
            # Extract pass information
            rise_time = pass_data.aos  # Acquisition of Signal (rise)
            set_time = pass_data.los   # Loss of Signal (set)
            
            # Get peak elevation and time from pass_data
            # orbit-predictor provides max_elevation_deg and max_elevation_date
            if hasattr(pass_data, 'max_elevation_date') and hasattr(pass_data, 'max_elevation_deg'):
                peak_time = pass_data.max_elevation_date
                max_elevation = pass_data.max_elevation_deg
            else:
                # Fallback: find peak by sampling
                peak_time, max_elevation = find_peak_elevation(
                    predictor, location, rise_time, set_time
                )
            
            pass_info = PassInfo(
                rise_time=rise_time,
                peak_time=peak_time,
                set_time=set_time,
                max_elevation=max_elevation,
                satellite_name=satellite_name,
                satellite_id=satellite_id
            )
            passes.append(pass_info)
            
            # Move to after this pass
            current_time = set_time + timedelta(seconds=1)
            
        except StopIteration:
            # No more passes
            break
        except Exception as e:
            error_msg = str(e)
            # If propagation limit exceeded or similar error, try sampling method
            if "limit" in error_msg.lower() or "propagation" in error_msg.lower():
                # Use sampling method as fallback
                try:
                    passes = compute_passes_by_sampling(
                        predictor, location, start_time, end_time, satellite_name, satellite_id, min_elevation_deg
                    )
                    break
                except Exception as e2:
                    # If sampling also fails, return what we have
                    break
            else:
                # For other errors, try sampling method
                try:
                    passes = compute_passes_by_sampling(
                        predictor, location, start_time, end_time, satellite_name, satellite_id, min_elevation_deg
                    )
                    break
                except Exception as e2:
                    # If both methods fail, return what we have
                    break
    
    return passes


def find_peak_elevation(predictor,
                       location: Location,
                       rise_time: datetime,
                       set_time: datetime,
                       num_samples: int = 50) -> Tuple[datetime, float]:
    """
    Find the peak elevation during a pass by sampling.
    
    Args:
        predictor: TLEPredictor instance
        location: Observer location
        rise_time: Pass start time
        set_time: Pass end time
        num_samples: Number of samples to take
    
    Returns:
        Tuple of (peak_time, max_elevation_deg)
    """
    duration = (set_time - rise_time).total_seconds()
    max_elevation = -90.0
    peak_time = rise_time
    
    for i in range(num_samples):
        # Sample time during the pass
        sample_time = rise_time + timedelta(seconds=duration * i / (num_samples - 1))
        
        try:
            # Get satellite position at this time
            position = predictor.get_position(sample_time)
            
            # Calculate elevation from observer location
            elevation = calculate_elevation(
                position.position_km,
                location.latitude_deg,
                location.longitude_deg,
                location.elevation_m
            )
            
            if elevation > max_elevation:
                max_elevation = elevation
                peak_time = sample_time
                
        except Exception:
            continue
    
    return peak_time, max_elevation


def calculate_elevation(satellite_position_km: Tuple[float, float, float],
                       observer_lat_deg: float,
                       observer_lon_deg: float,
                       observer_elevation_m: float) -> float:
    """
    Calculate elevation angle of satellite from observer location.
    Uses ECEF coordinates for proper calculation.
    
    Args:
        satellite_position_km: (x, y, z) position in ECI frame (km)
        observer_lat_deg: Observer latitude in degrees
        observer_lon_deg: Observer longitude in degrees
        observer_elevation_m: Observer elevation in meters
    
    Returns:
        Elevation angle in degrees
    """
    import math
    import numpy as np
    
    # Earth parameters
    R_earth = 6371.0  # km
    observer_alt_km = observer_elevation_m / 1000.0
    
    # Convert observer location to ECEF (Earth-Centered, Earth-Fixed)
    # This accounts for Earth's shape (WGS84 ellipsoid approximation)
    lat_rad = math.radians(observer_lat_deg)
    lon_rad = math.radians(observer_lon_deg)
    
    # WGS84 ellipsoid parameters
    a = 6378.137  # semi-major axis (km)
    e2 = 0.00669437999014  # first eccentricity squared
    
    # Calculate observer ECEF coordinates
    N = a / math.sqrt(1 - e2 * math.sin(lat_rad)**2)
    obs_x = (N + observer_alt_km) * math.cos(lat_rad) * math.cos(lon_rad)
    obs_y = (N + observer_alt_km) * math.cos(lat_rad) * math.sin(lon_rad)
    obs_z = (N * (1 - e2) + observer_alt_km) * math.sin(lat_rad)
    
    # Vector from observer to satellite (in ECI, need to account for Earth rotation)
    # For simplicity, assume ECI and ECEF are aligned at the current time
    # (This is approximate - proper calculation needs sidereal time)
    sat_x, sat_y, sat_z = satellite_position_km
    dx = sat_x - obs_x
    dy = sat_y - obs_y
    dz = sat_z - obs_z
    
    # Distance from observer to satellite
    distance = math.sqrt(dx**2 + dy**2 + dz**2)
    
    if distance == 0:
        return 90.0
    
    # Calculate elevation angle
    # First, calculate the local vertical (normal to Earth's surface at observer)
    # For a sphere approximation:
    obs_mag = math.sqrt(obs_x**2 + obs_y**2 + obs_z**2)
    if obs_mag == 0:
        return 0.0
    
    # Unit vector from Earth center to observer
    obs_unit = (obs_x / obs_mag, obs_y / obs_mag, obs_z / obs_mag)
    
    # Vector from observer to satellite
    sat_vec = (dx, dy, dz)
    sat_mag = distance
    
    # Dot product gives cosine of angle from vertical
    cos_angle = (sat_vec[0] * obs_unit[0] + sat_vec[1] * obs_unit[1] + sat_vec[2] * obs_unit[2]) / sat_mag
    
    # Elevation is 90 degrees minus the angle from vertical
    # cos(elevation) = sin(angle_from_vertical)
    elevation_rad = math.asin(max(-1.0, min(1.0, cos_angle)))
    elevation_deg = math.degrees(elevation_rad)
    
    return elevation_deg


def calculate_elevation_from_ecef(satellite_position_ecef: Tuple[float, float, float],
                                  observer_lat_deg: float,
                                  observer_lon_deg: float,
                                  observer_elevation_m: float) -> float:
    """
    Calculate elevation angle using ECEF coordinates (more accurate).
    
    Args:
        satellite_position_ecef: (x, y, z) position in ECEF frame (km)
        observer_lat_deg: Observer latitude in degrees
        observer_lon_deg: Observer longitude in degrees
        observer_elevation_m: Observer elevation in meters
    
    Returns:
        Elevation angle in degrees
    """
    import math
    
    # Earth parameters
    a = 6378.137  # WGS84 semi-major axis (km)
    e2 = 0.00669437999014  # WGS84 first eccentricity squared
    observer_alt_km = observer_elevation_m / 1000.0
    
    # Convert observer location to ECEF
    lat_rad = math.radians(observer_lat_deg)
    lon_rad = math.radians(observer_lon_deg)
    
    N = a / math.sqrt(1 - e2 * math.sin(lat_rad)**2)
    obs_x = (N + observer_alt_km) * math.cos(lat_rad) * math.cos(lon_rad)
    obs_y = (N + observer_alt_km) * math.cos(lat_rad) * math.sin(lon_rad)
    obs_z = (N * (1 - e2) + observer_alt_km) * math.sin(lat_rad)
    
    # Vector from observer to satellite (both in ECEF, so no rotation needed)
    sat_x, sat_y, sat_z = satellite_position_ecef
    dx = sat_x - obs_x
    dy = sat_y - obs_y
    dz = sat_z - obs_z
    
    # Distance from observer to satellite
    distance = math.sqrt(dx**2 + dy**2 + dz**2)
    
    if distance == 0:
        return 90.0
    
    # Calculate elevation: angle above local horizon
    # Local vertical (normal to ellipsoid at observer)
    obs_mag = math.sqrt(obs_x**2 + obs_y**2 + obs_z**2)
    if obs_mag == 0:
        return 0.0
    
    # Unit vector from Earth center to observer (local vertical)
    obs_unit = (obs_x / obs_mag, obs_y / obs_mag, obs_z / obs_mag)
    
    # Unit vector from observer to satellite
    sat_unit = (dx / distance, dy / distance, dz / distance)
    
    # Dot product gives cosine of angle from vertical
    cos_zenith = (sat_unit[0] * obs_unit[0] + sat_unit[1] * obs_unit[1] + sat_unit[2] * obs_unit[2])
    
    # Elevation = 90° - zenith angle
    # sin(elevation) = cos(zenith)
    elevation_rad = math.asin(max(-1.0, min(1.0, cos_zenith)))
    elevation_deg = math.degrees(elevation_rad)
    
    return elevation_deg


def compute_passes_by_sampling(predictor,
                               location: Location,
                               start_time: datetime,
                               end_time: datetime,
                               satellite_name: str = "Unknown",
                               satellite_id: str = "Unknown",
                               min_elevation_deg: float = 0.0) -> List[PassInfo]:
    """
    Compute passes by sampling elevation over time window.
    This is a fallback method if the standard API doesn't work.
    
    Args:
        predictor: TLEPredictor instance
        location: Observer location
        start_time: Start of time window
        end_time: End of time window
        min_elevation_deg: Minimum elevation threshold
    
    Returns:
        List of PassInfo objects
    """
    # Sample every minute
    sample_interval = timedelta(minutes=1)
    current_time = start_time
    
    passes = []
    in_pass = False
    pass_start = None
    pass_elevations = []
    pass_times = []
    
    while current_time <= end_time:
        try:
            position = predictor.get_position(current_time)
            # Use position_ecef if available (more accurate)
            if hasattr(position, 'position_ecef'):
                elevation = calculate_elevation_from_ecef(
                    position.position_ecef,
                    location.latitude_deg,
                    location.longitude_deg,
                    location.elevation_m
                )
            else:
                # Fallback to ECI calculation
                elevation = calculate_elevation(
                    position.position_km,
                    location.latitude_deg,
                    location.longitude_deg,
                    location.elevation_m
                )
            
            if elevation >= min_elevation_deg:
                if not in_pass:
                    # Pass starting
                    in_pass = True
                    pass_start = current_time
                    pass_elevations = [elevation]
                    pass_times = [current_time]
                else:
                    # Continue pass
                    pass_elevations.append(elevation)
                    pass_times.append(current_time)
            else:
                if in_pass:
                    # Pass ending
                    in_pass = False
                    if pass_start and len(pass_elevations) > 0:
                        # Find peak
                        max_idx = pass_elevations.index(max(pass_elevations))
                        peak_time = pass_times[max_idx]
                        max_elevation = pass_elevations[max_idx]
                        
                        pass_info = PassInfo(
                            rise_time=pass_start,
                            peak_time=peak_time,
                            set_time=current_time - sample_interval,
                            max_elevation=max_elevation,
                            satellite_name=satellite_name,
                            satellite_id=satellite_id
                        )
                        passes.append(pass_info)
                    
                    pass_start = None
                    pass_elevations = []
                    pass_times = []
                    
        except Exception:
            pass
        
        current_time += sample_interval
    
    # Handle pass that extends to end_time
    if in_pass and pass_start and len(pass_elevations) > 0:
        max_idx = pass_elevations.index(max(pass_elevations))
        peak_time = pass_times[max_idx]
        max_elevation = pass_elevations[max_idx]
        
        pass_info = PassInfo(
            rise_time=pass_start,
            peak_time=peak_time,
            set_time=end_time,
            max_elevation=max_elevation,
            satellite_name=satellite_name,
            satellite_id=satellite_id
        )
        passes.append(pass_info)
    
    return passes
