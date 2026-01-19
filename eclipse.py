"""Eclipse detection logic for satellites"""

from datetime import datetime
from typing import Tuple
import math


def is_in_eclipse(satellite_position: Tuple[float, float, float], 
                  sun_position: Tuple[float, float, float],
                  earth_radius_km: float = 6371.0) -> bool:
    """
    Determine if a satellite is in Earth's shadow (umbra).
    
    This uses a simplified geometric model: the satellite is in eclipse
    if it is behind Earth relative to the Sun, and the angle between
    the satellite-Earth vector and the Sun-Earth vector is such that
    the satellite is within Earth's shadow cone.
    
    Args:
        satellite_position: (x, y, z) position of satellite in ECI frame (km)
        sun_position: (x, y, z) position of Sun in ECI frame (km)
        earth_radius_km: Earth's radius in km (default 6371.0)
    
    Returns:
        True if satellite is in eclipse, False otherwise
    """
    # Convert to numpy-like calculations (using basic math)
    sat_x, sat_y, sat_z = satellite_position
    sun_x, sun_y, sun_z = sun_position
    
    # Vector from Earth center to satellite
    sat_distance = math.sqrt(sat_x**2 + sat_y**2 + sat_z**2)
    
    if sat_distance < earth_radius_km:
        # Satellite is below Earth's surface (shouldn't happen, but handle it)
        return True
    
    # Vector from Earth center to Sun
    sun_distance = math.sqrt(sun_x**2 + sun_y**2 + sun_z**2)
    
    # Normalize vectors
    sat_unit = (sat_x / sat_distance, sat_y / sat_distance, sat_z / sat_distance)
    sun_unit = (sun_x / sun_distance, sun_y / sun_distance, sun_z / sun_distance)
    
    # Dot product gives cosine of angle between vectors
    dot_product = sat_unit[0] * sun_unit[0] + sat_unit[1] * sun_unit[1] + sat_unit[2] * sun_unit[2]
    
    # If dot product is negative, satellite is on the opposite side of Earth from Sun
    # But we need to check if it's actually in the shadow cone
    if dot_product >= 0:
        # Satellite is on the sunlit side
        return False
    
    # Calculate the angle between satellite and sun vectors
    angle = math.acos(-dot_product)  # Negative because dot is negative
    
    # Calculate the half-angle of Earth's shadow cone
    # This is approximately arcsin(earth_radius / sun_distance)
    # For a more accurate model, we'd use the umbra cone angle
    shadow_half_angle = math.asin(earth_radius_km / sun_distance)
    
    # If the angle is less than the shadow half-angle plus a small margin,
    # the satellite is in the umbra
    # We also need to account for the satellite's distance
    # A more accurate check: is the satellite's projection within Earth's shadow?
    
    # Simplified check: if angle < shadow_half_angle and satellite is far enough
    # that it could be in shadow, consider it eclipsed
    if angle < shadow_half_angle + 0.01:  # Small margin for numerical precision
        return True
    
    # More accurate geometric check:
    # Project satellite position onto the line from Earth to Sun
    # Check if this projection is behind Earth and within the shadow cone
    
    # Vector projection of satellite onto sun direction
    projection_length = dot_product * sat_distance
    projection_vector = (
        sun_unit[0] * projection_length,
        sun_unit[1] * projection_length,
        sun_unit[2] * projection_length
    )
    
    # Distance from Earth center to projection point
    projection_distance = abs(projection_length)
    
    # If projection is behind Earth (negative) and far enough, check shadow cone
    if projection_length < 0 and projection_distance > earth_radius_km:
        # Calculate perpendicular distance from satellite to Earth-Sun line
        perp_vector = (
            sat_x - projection_vector[0],
            sat_y - projection_vector[1],
            sat_z - projection_vector[2]
        )
        perp_distance = math.sqrt(perp_vector[0]**2 + perp_vector[1]**2 + perp_vector[2]**2)
        
        # At the projection point, the shadow radius is approximately
        # earth_radius * (1 - projection_distance / sun_distance)
        # But for umbra, we use a simpler model
        shadow_radius_at_projection = earth_radius_km * (1 - abs(projection_length) / sun_distance)
        
        if perp_distance < shadow_radius_at_projection:
            return True
    
    return False


def check_eclipse_during_pass(pass_times: list, 
                              satellite_get_position_func,
                              sun_get_position_func) -> bool:
    """
    Check if satellite is in eclipse at any point during a pass.
    
    Args:
        pass_times: List of datetime objects during the pass (sampled times)
        satellite_get_position_func: Function that takes datetime and returns (x, y, z) position
        sun_get_position_func: Function that takes datetime and returns (x, y, z) position
    
    Returns:
        True if satellite is in eclipse at any point during the pass
    """
    for time in pass_times:
        sat_pos = satellite_get_position_func(time)
        sun_pos = sun_get_position_func(time)
        if is_in_eclipse(sat_pos, sun_pos):
            return True
    return False
