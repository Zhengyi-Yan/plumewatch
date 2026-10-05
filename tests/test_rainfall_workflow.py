"""Optional end-to-end Shiny upload/session tests; no browser launch required.

Run: PLUMEWATCH_WORKFLOW_TESTS=1 .venv/bin/python tests/test_rainfall_workflow.py
Uses the real upload HTTP endpoint, reactive server, maps, RF/U-Net and exports.
Weather responses are controlled by rainfall_dashboard_fixture.py. Set
PLUMEWATCH_TEST_UNET_PYTHON for an isolated U-Net test environment if needed.
"""
import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.getenv('PLUMEWATCH_WORKFLOW_TESTS') == '1', 'Set PLUMEWATCH_WORKFLOW_TESTS=1 for full-model session tests.')
class RainfallWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='plumewatch-workflow-')
        cls.folder = Path(cls.temp.name)
        (cls.folder / 'mode').write_text('ok')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            cls.port = listener.getsockname()[1]
        cls.url = f'http://127.0.0.1:{cls.port}/'
        cls.log = (cls.folder / 'server.log').open('w')
        cls.server = subprocess.Popen([str(ROOT / '.venv/bin/python'),
                                       str(ROOT / 'tests/rainfall_dashboard_fixture.py'), str(cls.folder), str(cls.port)],
                                      cwd=ROOT, stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            try:
                with urlopen(cls.url, timeout=1) as response:
                    cls.html = response.read().decode()
                    break
            except OSError:
                if cls.server.poll() is not None:
                    raise RuntimeError((cls.folder / 'server.log').read_text())
                time.sleep(.1)
        else:
            raise RuntimeError('Test server did not start.')

    @classmethod
    def stop_server(cls):
        if cls.server.poll() is None:
            cls.server.terminate()
            cls.server.wait(timeout=10)

    @classmethod
    def tearDownClass(cls):
        cls.stop_server()
        cls.log.close()
        log = (cls.folder / 'server.log').read_text()
        cls.temp.cleanup()
        if 'Traceback' in log:
            raise AssertionError(log)

    def setUp(self):
        self.mode('ok')
        self.ws_context = connect(f'ws://127.0.0.1:{self.port}/websocket/')
        self.ws = self.ws_context.__enter__()
        self.values, self.custom, self.responses = {}, {}, {}
        self.tag, self.run_count, self.retry_count = 0, 0, 0
        self.ws.recv(timeout=5)  # Session configuration.
        data = {'acquisition_date:shiny.date': None, 'example:shiny.action': 0,
                'run:shiny.action': 0, 'retry_rainfall:shiny.action': 0, 'model_notes:shiny.action': 0,
                'model': 'rf', 'threshold': 70, 'upload:shiny.file': None}
        for name in ['rainfall_content', 'status', 'scene_name', 'map_title', 'scene_details',
                     'plume_area', 'water_area', 'land_area', 'disagreement', 'download']:
            data[f'.clientdata_output_{name}_hidden'] = False
        self.send('init', data=data)
        self.wait_text('status', 'Open a supported')

    def tearDown(self):
        self.ws_context.__exit__(None, None, None)

    def mode(self, value):
        (self.folder / 'mode').write_text(value)

    def calls(self):
        path = self.folder / 'calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def send(self, method, **data):
        self.ws.send(json.dumps({'method': method, **data}))

    def receive(self, timeout=10):
        message = json.loads(self.ws.recv(timeout=timeout))
        self.values.update(message.get('values', {}))
        self.custom.update(message.get('custom', {}))
        if message.get('errors'):
            self.fail(str(message['errors']))
        if 'response' in message:
            response = message['response']
            self.assertNotIn('error', response)
            self.responses[response['tag']] = response.get('value')
        # Simulate the standard date binding acknowledging ui.update_date.
        for item in message.get('inputMessages', []):
            if item['id'] == 'acquisition_date' and 'value' in item['message']:
                self.date(item['message']['value'])
        return message

    def wait_until(self, predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail(f'Timed out. Values: {self.values}; controls: {self.custom.get("pw-controls")}')
            try:
                self.receive(timeout=max(.1, deadline - time.monotonic()))
            except TimeoutError:
                self.fail(f'Timed out. Values: {self.values}; controls: {self.custom.get("pw-controls")}')

    def wait_text(self, name, text, timeout=30):
        self.wait_until(lambda: text in str(self.values.get(name, '')), timeout)

    def rpc(self, method, args):
        self.tag += 1
        self.send(method, tag=self.tag, args=args)
        self.wait_until(lambda: self.tag in self.responses)
        return self.responses.pop(self.tag)

    def upload(self, name='nz', *, valid=True):
        path = self.folder / f'{name}.tif'
        meta = self.rpc('uploadInit', [[{'name': path.name, 'size': path.stat().st_size, 'type': 'image/tiff'}]])
        self.values.pop('status', None)
        with urlopen(Request(self.url + meta['uploadUrl'], data=path.read_bytes(), method='POST'), timeout=5) as response:
            self.assertEqual(response.status, 200)
        self.rpc('uploadEnd', [meta['jobId'], 'upload'])
        self.wait_text('status', 'Scene ready' if valid else 'projected CRS')

    def date(self, value):
        self.send('update', data={'acquisition_date:shiny.date': value or None})

    def classify(self):
        self.run_count += 1
        self.values.pop('status', None)
        self.send('update', data={'run:shiny.action': self.run_count})
        self.wait_text('status', 'Classification ready', timeout=60)
        self.wait_until(lambda: all('km²' in str(self.values.get(key)) for key in ['plume_area', 'water_area', 'land_area']))
        self.assertEqual(set(self.custom['pw-result']), {'rf', 'unet'})
        self.assertIn('rgb', self.custom['pw-scene'])
        self.assertIn('bounds', self.custom['pw-scene'])

    def test_normal_missing_date_cache_and_existing_outputs(self):
        count = len(self.calls())
        self.date('2021-02-14')
        self.wait_text('rainfall_content', 'Open a scene')
        self.assertEqual(len(self.calls()), count)
        self.upload()
        self.wait_text('rainfall_content', 'Enter the Sentinel-2 acquisition date')
        self.assertEqual(len(self.calls()), count)
        self.classify()
        before = {key: self.values[key] for key in ['plume_area', 'water_area', 'land_area']}
        self.mode('slow')
        self.date('2021-02-14')
        self.wait_text('rainfall_content', 'Loading historical rainfall')
        self.wait_text('rainfall_content', '28.0 mm')
        html = str(self.values['rainfall_content'])
        self.assertIn('7.0 mm', html)
        self.assertIn('18.0 mm', html)
        self.assertIn('2021-02-07 to 2021-02-13', html)
        self.assertEqual(before, {key: self.values[key] for key in before})
        self.date(None)
        self.wait_text('rainfall_content', 'Enter the Sentinel-2 acquisition date')
        count = len(self.calls())
        self.date('2021-02-14')
        self.wait_text('rainfall_content', '28.0 mm')
        self.assertEqual(len(self.calls()), count)
        self.send('update', data={'model': 'unet'})
        self.wait_text('disagreement', 'vs RF')
        self.wait_until(lambda: self.custom.get('pw-style', {}).get('model') == 'unet')
        self.wait_until(lambda: bool(self.values.get('download')))
        with urlopen(urljoin(self.url, self.values['download']), timeout=10) as response:
            self.assertEqual(response.read(2), b'PK')

    def test_other_geographic_location_and_upload_resets_date(self):
        self.upload()
        self.date('2021-02-14')
        self.wait_text('rainfall_content', '28.0 mm')
        self.upload('berlin')
        self.wait_text('rainfall_content', 'Enter the Sentinel-2 acquisition date')
        self.date('2021-02-14')
        self.wait_text('rainfall_content', 'Europe/Berlin')
        lat, lon = self.calls()[-1]['location']
        self.assertAlmostEqual(lat, 52.52, delta=.05)
        self.assertAlmostEqual(lon, 13.39, delta=.05)
        self.classify()

    @unittest.skipUnless(os.getenv('PLUMEWATCH_LIVE_WEATHER_TESTS') == '1', 'Opt in to live Open-Meteo requests.')
    def test_live_archive_for_two_uploaded_geographic_scenes(self):
        self.mode('live')
        for name, zone in [('nz', 'Pacific/Auckland'), ('berlin', 'Europe/Berlin')]:
            self.upload(name)
            self.date('2021-02-14')
            self.wait_text('rainfall_content', zone)
            self.assertIn('2021-02-07 to 2021-02-13', str(self.values['rainfall_content']))
            self.assertEqual(str(self.values['rainfall_content']).count(' mm</td>'), 3)
            self.classify()

    def test_network_failure_retains_plume_and_retry_recovers(self):
        self.upload()
        self.mode('network')
        self.date('2021-02-14')
        self.wait_text('rainfall_content', 'Could not reach Open-Meteo')
        self.classify()
        self.assertNotIn('rainfall-table', str(self.values['rainfall_content']))
        self.mode('ok')
        self.retry_count += 1
        self.send('update', data={'retry_rainfall:shiny.action': self.retry_count})
        self.wait_text('rainfall_content', '28.0 mm')
        self.assertIn('km²', self.values['plume_area'])

    def test_invalid_dates_no_data_malformed_and_stale_response(self):
        self.upload()
        for value in ['bad-date', '2021-02-30', '1940-01-07', '2999-01-01']:
            self.values.pop('rainfall_content', None)
            count = len(self.calls())
            self.date(value)
            self.wait_until(lambda: ('Enter the Sentinel-2 acquisition date' in str(self.values.get('rainfall_content')) or
                                    'Use an acquisition date' in str(self.values.get('rainfall_content'))))
            self.assertEqual(len(self.calls()), count)
        for mode, message in [('missing_data', 'missing or invalid'), ('malformed', 'incomplete rainfall response')]:
            self.mode(mode)
            self.date(None)
            self.wait_text('rainfall_content', 'Enter the Sentinel-2 acquisition date')
            self.date('2021-02-14')
            self.wait_text('rainfall_content', message)
            self.assertNotIn('rainfall-table', str(self.values['rainfall_content']))
        self.mode('slow')
        self.date('2021-02-15')
        self.wait_text('rainfall_content', 'Loading historical rainfall')
        self.date('2021-02-14')
        self.wait_text('rainfall_content', '28.0 mm')
        self.assertIn('Before 2021-02-14', str(self.values['rainfall_content']))
        self.assertNotIn('70.0 mm', str(self.values['rainfall_content']))

    def test_location_failure_isolated_and_missing_crs_keeps_existing_validation(self):
        self.mode('no_location')
        self.upload()
        count = len(self.calls())
        self.date('2021-02-14')
        self.wait_text('rainfall_content', 'no usable geographic location')
        self.assertEqual(len(self.calls()), count)
        self.classify()
        self.upload('no_crs', valid=False)
        self.wait_until(lambda: self.custom.get('pw-controls', {}).get('ready') is False)
        self.assertNotIn('rainfall-table', str(self.values['rainfall_content']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
