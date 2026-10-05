"""Open-Meteo antecedent precipitation context; never used by plume models."""
import json
import math
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from rasterio.warp import transform

ARCHIVE_URL = 'https://archive-api.open-meteo.com/v1/archive'
MIN_ACQUISITION_DATE = date(1940, 1, 8)  # A full seven-day window from 1940-01-01.
REQUEST_TIMEOUT = 15


class RainfallError(ValueError):
    """A useful user-facing reason why rainfall context is unavailable."""


def acquisition_date(value, *, today=None):
    if value is None or value == '':
        raise RainfallError('Enter the Sentinel-2 acquisition date to retrieve rainfall.')
    try:
        if isinstance(value, datetime):
            raise ValueError('Expected a calendar date.')
        result = value if isinstance(value, date) else date.fromisoformat(value)
    except (TypeError, ValueError):
        raise RainfallError('Enter a valid Sentinel-2 acquisition date (YYYY-MM-DD).') from None
    today = today or datetime.now(timezone.utc).date()
    if result < MIN_ACQUISITION_DATE or result > today:
        raise RainfallError(f'Use an acquisition date between {MIN_ACQUISITION_DATE.isoformat()} '
                            f'and {today.isoformat()}. Recent archive data may still be unavailable.')
    return result


def valid_location(location):
    try:
        lat, lon = location
        if (isinstance(lat, bool) or isinstance(lon, bool) or
                not math.isfinite(lat) or not math.isfinite(lon) or
                not -90 <= lat <= 90 or not -180 <= lon <= 180):
            raise ValueError('Invalid coordinates.')
        return float(lat), float(lon)
    except (TypeError, ValueError, OverflowError):
        raise RainfallError('The raster has no usable geographic location for rainfall.') from None


def scene_location(src):
    """Transform the native raster centre to WGS84, without changing the raster."""
    try:
        if not src.crs or src.transform.is_identity:
            return None
        x, y = src.transform * (src.width / 2, src.height / 2)
        lon, lat = transform(src.crs, 'EPSG:4326', [x], [y])
        return valid_location((lat[0], lon[0]))
    except Exception:
        # Weather metadata must not introduce another reason to fail scene loading.
        return None


def parse_rainfall(payload, observed):
    """Require all seven dates and finite mm values; missing data never become zero."""
    days = [(observed - timedelta(days=offset)).isoformat() for offset in range(7, 0, -1)]
    if not isinstance(payload, dict) or payload.get('error'):
        raise RainfallError('Open-Meteo returned no usable historical rainfall data.')
    daily, units = payload.get('daily'), payload.get('daily_units')
    if not isinstance(daily, dict) or not isinstance(units, dict):
        raise RainfallError('Open-Meteo returned an incomplete rainfall response.')
    amounts = daily.get('precipitation_sum')
    if (daily.get('time') != days or not isinstance(amounts, list) or len(amounts) != 7 or
            units.get('precipitation_sum') != 'mm'):
        raise RainfallError('Open-Meteo did not return all seven preceding days in millimetres.')
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or
           not math.isfinite(value) or value < 0 for value in amounts):
        raise RainfallError('Rainfall data are missing or invalid for one or more preceding days.')
    zone = payload.get('timezone')
    if not isinstance(zone, str) or not zone:
        raise RainfallError('Open-Meteo did not identify the local calendar-day timezone.')
    return {'acquisition_date': observed.isoformat(), 'start_date': days[0], 'end_date': days[-1],
            'timezone': zone, 'daily_dates': days, 'daily_mm': amounts,
            'totals_mm': {n: math.fsum(amounts[-n:]) for n in (1, 3, 7)}}


def fetch_rainfall(location, observed):
    """One keyless archive request for seven complete days in the scene's timezone."""
    observed = acquisition_date(observed)
    lat, lon = valid_location(location)
    query = urlencode({'latitude': lat, 'longitude': lon,
                       'start_date': (observed - timedelta(days=7)).isoformat(),
                       'end_date': (observed - timedelta(days=1)).isoformat(),
                       'daily': 'precipitation_sum', 'timezone': 'auto',
                       'precipitation_unit': 'mm', 'cell_selection': 'nearest'})
    request = Request(ARCHIVE_URL + '?' + query, headers={'User-Agent': 'PlumeWatch/1.0'})
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            payload = json.load(response)
    except HTTPError as error:
        code = error.code
        error.close()
        raise RainfallError(f'Open-Meteo could not serve this scene/date (HTTP {code}). '
                            'Recent archive data may not yet be available; try again later.') from None
    except (URLError, OSError, TimeoutError):
        raise RainfallError('Could not reach Open-Meteo. Check the connection and retry rainfall.') from None
    except (ValueError, UnicodeError):
        raise RainfallError('Open-Meteo returned a malformed rainfall response. Try again later.') from None
    result = parse_rainfall(payload, observed)
    result['location'] = (lat, lon)
    return result
