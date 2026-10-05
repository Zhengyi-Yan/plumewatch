"""Browser-test server: real raster processing/models, controlled weather responses."""
import json
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import rasterio
from rasterio.transform import from_origin
import app as dashboard
from processing import BANDS
from rainfall import RainfallError, fetch_rainfall as fetch_live_rainfall, parse_rainfall
if os.getenv('PLUMEWATCH_TEST_UNET_PYTHON'):
    import processing
    processing.UNET_PYTHON = Path(os.environ['PLUMEWATCH_TEST_UNET_PYTHON'])

folder, port = Path(sys.argv[1]), int(sys.argv[2])
for name, crs, origin in [('nz', 'EPSG:32760', (320000, 5430000)),
                          ('berlin', 'EPSG:32633', (391000, 5820000)),
                          ('no_crs', None, (320000, 5430000))]:
    data = np.full((12, 32, 32), .025, dtype='float32')
    data[2, :, 16:] = .08
    data[10] = 6
    data[11] = 1
    with rasterio.open(folder / f'{name}.tif', 'w', driver='GTiff', count=12, height=32, width=32,
                       dtype='float32', transform=from_origin(*origin, 10, 10), crs=crs, nodata=-9999) as dst:
        dst.write(data)
        dst.descriptions = tuple(BANDS)

dashboard.EXAMPLE = folder / ('nz.tif' if os.getenv('PLUMEWATCH_TEST_EXAMPLE') else 'no_example.tif')
prepare = dashboard.prepare_scene


def prepare_scene(path):
    scene = prepare(path)
    if (folder / 'mode').read_text().strip() == 'no_location':
        scene['rainfall_location'] = None
    return scene


def fetch_rainfall(location, observed):
    mode = (folder / 'mode').read_text().strip()
    with (folder / 'calls.jsonl').open('a') as stream:
        stream.write(json.dumps({'location': location, 'date': observed.isoformat(), 'mode': mode}) + '\n')
    if mode == 'live':
        return fetch_live_rainfall(location, observed)
    time.sleep(2 if mode == 'slow' else .3)
    if mode == 'network':
        raise RainfallError('Could not reach Open-Meteo. Check the connection and retry rainfall.')
    dates = [(observed - timedelta(days=n)).isoformat() for n in range(7, 0, -1)]
    amounts = [1, 2, 3, 4, 5, 6, 7] if observed.day == 14 else [10] * 7
    payload = {'timezone': 'Pacific/Auckland' if location[0] < 0 else 'Europe/Berlin',
               'daily': {'time': dates, 'precipitation_sum': amounts},
               'daily_units': {'precipitation_sum': 'mm'}}
    if mode == 'missing_data':
        payload['daily']['precipitation_sum'][2] = None
    if mode == 'malformed':
        payload['daily'] = []
    return parse_rainfall(payload, observed)


dashboard.prepare_scene = prepare_scene
dashboard.fetch_rainfall = fetch_rainfall
import uvicorn
uvicorn.run(dashboard.app, host='127.0.0.1', port=port, log_level='warning')
