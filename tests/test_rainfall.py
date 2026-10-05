"""Deterministic archive, geographic metadata and antecedent-window checks."""
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from processing import BANDS, prepare_scene
from rainfall import (RainfallError, acquisition_date, fetch_rainfall, parse_rainfall,
                      scene_location, valid_location)


def response():
    return {'timezone': 'Pacific/Auckland', 'daily_units': {'precipitation_sum': 'mm'},
            'daily': {'time': [f'2021-02-{n:02d}' for n in range(7, 14)],
                      'precipitation_sum': [1, 2, 3, 4, 5, 6, 7]}}


class RainfallTest(unittest.TestCase):
    def test_windows_exclude_acquisition_day(self):
        result = parse_rainfall(response(), date(2021, 2, 14))
        self.assertEqual(result['totals_mm'], {1: 7, 3: 18, 7: 28})
        self.assertEqual(result['start_date'], '2021-02-07')
        self.assertEqual(result['end_date'], '2021-02-13')

    def test_date_validation(self):
        for value in [None, '', 'garbage', '2021-02-30', '1940-01-07', '2022-01-01', 123]:
            with self.subTest(value=value), self.assertRaises(RainfallError):
                acquisition_date(value, today=date(2021, 12, 31))
        self.assertEqual(acquisition_date('1940-01-08'), date(1940, 1, 8))
        self.assertEqual(acquisition_date(date(2020, 2, 29)), date(2020, 2, 29))

    def test_request_uses_scene_location_local_days_and_mm(self):
        for location in [(-41.28, 174.86), (52.52, 13.4)]:
            with self.subTest(location=location), patch('rainfall.urlopen') as opened:
                opened.return_value.__enter__.return_value = io.StringIO(json.dumps(response()))
                result = fetch_rainfall(location, '2021-02-14')
                request = opened.call_args.args[0]
                params = parse_qs(urlparse(request.full_url).query)
                self.assertEqual(urlparse(request.full_url).netloc, 'archive-api.open-meteo.com')
                self.assertEqual(params['latitude'], [str(location[0])])
                self.assertEqual(params['longitude'], [str(location[1])])
                self.assertEqual(params['start_date'], ['2021-02-07'])
                self.assertEqual(params['end_date'], ['2021-02-13'])
                self.assertEqual(params['timezone'], ['auto'])
                self.assertEqual(params['daily'], ['precipitation_sum'])
                self.assertEqual(params['precipitation_unit'], ['mm'])
                self.assertNotIn('apikey', params)
                self.assertEqual(opened.call_args.kwargs['timeout'], 15)
                self.assertEqual(result['location'], location)

    def test_bad_inputs_do_not_make_network_requests(self):
        with patch('rainfall.urlopen') as opened:
            for location, observed in [(None, '2021-02-14'), ((91, 20), '2021-02-14'),
                                       ((0, 0), None), ((0, 0), '1940-01-01')]:
                with self.assertRaises(RainfallError):
                    fetch_rainfall(location, observed)
            opened.assert_not_called()

    def test_network_http_timeout_and_malformed_json(self):
        errors = [URLError('offline'), TimeoutError(), OSError('connection reset'),
                  HTTPError('https://example.test', 400, 'bad date', {}, None),
                  HTTPError('https://example.test', 429, 'rate limit', {}, None)]
        for error in errors:
            with self.subTest(error=error), patch('rainfall.urlopen', side_effect=error):
                with self.assertRaises(RainfallError):
                    fetch_rainfall((-41, 174), '2021-02-14')
        with patch('rainfall.urlopen') as opened:
            opened.return_value.__enter__.return_value = io.StringIO('{broken')
            with self.assertRaisesRegex(RainfallError, 'malformed'):
                fetch_rainfall((-41, 174), '2021-02-14')

    def test_missing_malformed_and_nonfinite_values_never_become_zero(self):
        bad = [None, [], {}, {'error': True}]
        for value in [None, -1, float('nan'), float('inf'), '3', True]:
            payload = response()
            payload['daily']['precipitation_sum'][3] = value
            bad.append(payload)
        for field, value in [('time', ['2021-02-14'] * 7), ('time', []),
                             ('precipitation_sum', [1] * 6), ('precipitation_sum', {})]:
            payload = response()
            payload['daily'][field] = value
            bad.append(payload)
        for field, value in [('daily', None), ('daily_units', {'precipitation_sum': 'inch'}),
                             ('timezone', None)]:
            payload = response()
            payload[field] = value
            bad.append(payload)
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(RainfallError):
                parse_rainfall(payload, date(2021, 2, 14))
        payload = response()
        payload['daily']['precipitation_sum'] = [0] * 7
        self.assertEqual(parse_rainfall(payload, date(2021, 2, 14))['totals_mm'], {1: 0, 3: 0, 7: 0})

    def test_month_year_and_leap_day_boundaries(self):
        from datetime import timedelta
        for observed in [date(2021, 1, 1), date(2020, 3, 1), date(1940, 1, 8)]:
            payload = response()
            payload['daily']['time'] = [(observed - timedelta(days=n)).isoformat() for n in range(7, 0, -1)]
            result = parse_rainfall(payload, observed)
            self.assertEqual(result['totals_mm'][7], 28)
            self.assertNotIn(observed.isoformat(), result['daily_dates'])

    def test_raster_centres_in_new_zealand_and_germany(self):
        for crs, origin, expected in [('EPSG:32760', (320000, 5430000), (-41.26, 174.85)),
                                      ('EPSG:32633', (391000, 5820000), (52.52, 13.39))]:
            with self.subTest(crs=crs), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'scene.tif'
                data = np.full((12, 32, 32), .025, dtype='float32')
                data[10] = 6
                data[11] = 1
                with rasterio.open(path, 'w', driver='GTiff', count=12, height=32, width=32,
                                   dtype='float32', crs=crs, transform=from_origin(*origin, 10, 10)) as dst:
                    dst.write(data)
                    dst.descriptions = tuple(BANDS)
                original = path.read_bytes()
                scene = prepare_scene(path)
                lat, lon = scene['rainfall_location']
                self.assertAlmostEqual(lat, expected[0], delta=.05)
                self.assertAlmostEqual(lon, expected[1], delta=.05)
                self.assertEqual(path.read_bytes(), original)

    def test_missing_crs_is_safe_for_weather_and_existing_loader_rejects_it(self):
        with MemoryFile() as memory:
            with memory.open(driver='GTiff', count=1, width=2, height=2, dtype='float32',
                             transform=from_origin(320000, 5430000, 10, 10)) as src:
                self.assertIsNone(scene_location(src))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'no_crs.tif'
            with rasterio.open(path, 'w', driver='GTiff', count=12, width=2, height=2,
                               dtype='float32', transform=from_origin(320000, 5430000, 10, 10)) as dst:
                dst.descriptions = tuple(BANDS)
            with self.assertRaisesRegex(ValueError, 'projected CRS'):
                prepare_scene(path)

    def test_weather_transform_failure_is_isolated(self):
        with MemoryFile() as memory:
            with memory.open(driver='GTiff', count=1, width=2, height=2, dtype='float32',
                             crs='EPSG:32760', transform=from_origin(320000, 5430000, 10, 10)) as src:
                with patch('rainfall.transform', side_effect=RuntimeError('projection failed')):
                    self.assertIsNone(scene_location(src))
        for location in [None, (float('nan'), 20), (20, 181), (True, 1), ('20', 1)]:
            with self.assertRaises(RainfallError):
                valid_location(location)


if __name__ == '__main__':
    unittest.main()
