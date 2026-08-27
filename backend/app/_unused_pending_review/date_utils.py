"""
Date utility functions for rolling date window calculations.
"""
from datetime import datetime, timedelta
from typing import Tuple, Optional
from enum import Enum

class PublicationFilter(str, Enum):
    ANY_TIME = "ANY_TIME"
    LAST_3_YEARS = "LAST_3_YEARS"
    LAST_5_YEARS = "LAST_5_YEARS"
    LAST_10_YEARS = "LAST_10_YEARS"

def get_date_window(publication_filter: str, reference_date: Optional[datetime] = None) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Calculate rolling date window based on publication filter.
    
    Args:
        publication_filter: One of ANY_TIME, LAST_3_YEARS, LAST_5_YEARS, LAST_10_YEARS
        reference_date: Reference date for calculation (defaults to current time)
    
    Returns:
        Tuple of (start_date, end_date) where end_date is always the reference date
        Returns (None, None) for ANY_TIME
    """
    if reference_date is None:
        reference_date = datetime.utcnow()
    
    if publication_filter == PublicationFilter.ANY_TIME.value:
        return None, None
    
    if publication_filter == PublicationFilter.LAST_3_YEARS.value:
        start_date = reference_date - timedelta(days=3*365)
        return start_date, reference_date
    
    if publication_filter == PublicationFilter.LAST_5_YEARS.value:
        start_date = reference_date - timedelta(days=5*365)
        return start_date, reference_date
    
    if publication_filter == PublicationFilter.LAST_10_YEARS.value:
        start_date = reference_date - timedelta(days=10*365)
        return start_date, reference_date
    
    # Unknown filter - treat as ANY_TIME
    return None, None

def normalize_publication_date(date_str: str) -> Optional[datetime]:
    """
    Normalize patent publication date string to datetime object.
    
    Handles various date formats from patent databases:
    - YYYY-MM-DD
    - YYYYMMDD
    - YYYY-MM
    - YYYY
    
    Args:
        date_str: Date string from patent metadata
    
    Returns:
        datetime object or None if parsing fails
    """
    if not date_str:
        return None
    
    date_str = date_str.strip()
    
    # Try common formats
    formats = [
        "%Y-%m-%d",
        "%Y%m%d",
        "%Y-%m",
        "%Y",
        "%Y/%m/%d",
        "%m/%d/%Y",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    
    return None

def is_date_in_window(date_str: str, start_date: Optional[datetime], end_date: Optional[datetime]) -> bool:
    """
    Check if a patent publication date falls within the date window.
    
    Args:
        date_str: Publication date string
        start_date: Window start date (inclusive)
        end_date: Window end date (inclusive)
    
    Returns:
        True if date is within window or if window is not specified
    """
    if start_date is None and end_date is None:
        return True
    
    pub_date = normalize_publication_date(date_str)
    if pub_date is None:
        # If we can't parse the date, conservatively include it
        return True
    
    if start_date and pub_date < start_date:
        return False
    
    if end_date and pub_date > end_date:
        return False
    
    return True
