"""Configuration file handling for Space-Track credentials"""

import configparser
import os
from pathlib import Path


def get_spacetrack_credentials(config_path=None):
    """
    Read Space-Track credentials from config.ini file.
    
    Args:
        config_path: Path to config.ini file. If None, looks for config.ini
                     in the current directory or user's home directory.
    
    Returns:
        tuple: (username, password) or (None, None) if not found
    """
    if config_path is None:
        # Try current directory first, then home directory
        possible_paths = [
            Path.cwd() / "config.ini",
            Path.home() / "config.ini",
            Path(__file__).parent.parent / "config.ini",
        ]
        
        for path in possible_paths:
            if path.exists():
                config_path = path
                break
        else:
            return None, None
    
    if not os.path.exists(config_path):
        return None, None
    
    config = configparser.ConfigParser()
    try:
        config.read(config_path)
        if 'spacetrack' in config:
            username = config.get('spacetrack', 'username', fallback=None)
            password = config.get('spacetrack', 'password', fallback=None)
            return username, password
    except Exception:
        pass
    
    return None, None
