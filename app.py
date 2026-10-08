"""PlumeWatch three-model review dashboard. Run: shiny run --reload app.py"""
import asyncio
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from shiny import App, reactive, render, ui
from processing import (EXAMPLE, MAX_BYTES, classify_rf, classify_unet, classify_svm, disagreement_km2,
                        make_download, prepare_scene, summary)
from rainfall import MIN_ACQUISITION_DATE, RainfallError, acquisition_date, fetch_rainfall, valid_location

ROOT = Path(__file__).resolve().parent
POOL = ThreadPoolExecutor(max_workers=2)


def class_row(name, css_class, output_id):
    return ui.div(ui.span(class_='legend-dot ' + css_class), ui.span(name),
                  ui.span(ui.output_text(output_id, inline=True), class_='class-value'), class_='class-row')


app_ui = ui.page_fluid(
    ui.tags.head(
        ui.tags.meta(name='viewport', content='width=device-width, initial-scale=1'),
        ui.tags.link(rel='preconnect', href='https://fonts.googleapis.com'),
        ui.tags.link(rel='preconnect', href='https://fonts.gstatic.com', crossorigin='anonymous'),
        ui.tags.link(rel='stylesheet', href='https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap'),
        ui.tags.link(rel='stylesheet', href='https://cdn.jsdelivr.net/npm/@phosphor-icons/web@2.1.2/src/light/style.css'),
        ui.tags.link(rel='stylesheet', href='leaflet.css'),
        ui.tags.link(rel='stylesheet', href='app.css?v=20261008-ui-cleanup'),
        ui.tags.script(src='leaflet.js'),
        ui.tags.script(src='app.js?v=20261008-ui-cleanup', defer=True)),
    ui.div(
        ui.tags.aside(
            ui.div(ui.span('plumewatch', class_='brand-word'), class_='brand'),
            ui.p('SATELLITE INSIGHT STUDIO', class_='brand-caption'),
            ui.div(class_='nav-rule'), ui.p('WORKSPACE', class_='nav-label'),
            ui.tags.nav(
                ui.tags.a(ui.tags.img(src='blue/overview.svg', alt='', class_='nav-icon'), 'Overview', href='#overview', class_='nav-link active'),
                ui.tags.a(ui.tags.img(src='blue/scenes.svg', alt='', class_='nav-icon'), 'Scenes', href='#workspace', class_='nav-link'),
                ui.input_action_button('model_notes', ui.span(ui.tags.img(src='blue/model-notes.svg', alt='', class_='nav-icon'), 'Model notes'),
                                       class_='nav-link nav-button'),
                ui.tags.a(ui.tags.img(src='blue/exports.svg', alt='', class_='nav-icon'), 'Exports', href='#export-actions', class_='nav-link'),
                class_='side-nav'),
            class_='site-sidebar'),
        ui.tags.main(
            ui.div(ui.p('COASTAL MONITORING', class_='eyebrow'),
                   ui.h1('A clearer view of coastal plumes.'),
                   ui.p('Sentinel-2 image classification and georeferenced exports.', class_='intro'),
                   class_='hero', id='overview'),
            ui.div(ui.div(ui.p('SCENE WORKSPACE', class_='eyebrow'),
                          ui.h2(ui.output_text('scene_name', inline=True)),
                          ui.p(ui.output_text('scene_details', inline=True), class_='scene-detail'),
                          class_='workspace-title'),
                   ui.div(ui.input_action_button('example', ui.span('Load example scene',
                                     ui.span(ui.tags.img(src='blue/arrow-blue.svg', alt=''), class_='action-well'),
                                     class_='action-label'), class_='example-button'),
                          ui.div(ui.input_file('upload', None, accept=['.tif', '.tiff'],
                                               button_label='Open a scene', placeholder='GEE GeoTIFF'),
                                 class_='scene-upload'), class_='workspace-actions'),
                   class_='workspace-heading', id='workspace'),
            ui.div(ui.input_date('acquisition_date', 'Sentinel-2 acquisition date', value='',
                                 min=MIN_ACQUISITION_DATE, format='yyyy-mm-dd'),
                   class_='scene-date'),
            ui.div(
                ui.div(
                    ui.div(
                    ui.div(ui.span(ui.output_text('map_title', inline=True)),
                           ui.span('SENTINEL-2 · 10 BANDS', class_='map-source'), class_='map-topbar'),
                    ui.div(ui.div(id='map', role='region', aria_label='Satellite scene map'),
                           ui.div(id='pixel-info', class_='pixel-info', hidden=True),
                           ui.div(
                               ui.span('Original', class_='swipe-label swipe-original'),
                               ui.span('Classification', class_='swipe-label swipe-classification'),
                               ui.div(class_='swipe-divider', id='swipe-divider'),
                               ui.tags.input(id='swipe-position', type='range', min=0, max=100, value=50,
                                             aria_label='Original versus classification comparison position'),
                               ui.div(ui.span('‹', aria_hidden='true'), ui.span('›', aria_hidden='true'),
                                      id='swipe-handle', class_='swipe-handle', aria_hidden='true'),
                               id='swipe-control', hidden=True),
                           class_='map-stage'),
                    ui.div(
                    ui.div(ui.tags.button('Original', type='button', data_view='original'),
                           ui.tags.button('Overlay', type='button', data_view='overlay', aria_pressed='true'),
                           ui.tags.button('Classes', type='button', data_view='classes'),
                           ui.tags.button('Swipe', type='button', data_view='swipe'),
                           ui.tags.button('Plume score', type='button', data_view='score'),
                           ui.tags.button('Disagreement', type='button', data_view='disagreement'),
                           class_='map-switch'),
                    ui.div(ui.span('Disagreement area: ', ui.output_text('disagreement', inline=True),
                                   class_='disagreement-area'),
                           ui.span('Model disagreement does not indicate which model is correct.'),
                           id='disagreement-summary', class_='disagreement-summary', hidden=True),
                    ui.div(ui.tags.label('Score appearance', **{'for': 'score-style'}),
                           ui.tags.select(ui.tags.option('Soft colour ramp', value='soft'),
                                          ui.tags.option('Original colours', value='original'),
                                          id='score-style'),
                           ui.div(ui.tags.label(ui.tags.input(id='score-smoothing', type='checkbox', checked=True),
                                                ' Smooth display')),
                           ui.tags.label('Smoothing strength', **{'for': 'score-strength'}),
                           ui.tags.select(ui.tags.option('Light · 20 m', value='light'),
                                          ui.tags.option('Medium · 50 m', value='medium', selected=True),
                                          ui.tags.option('Strong · 100 m', value='strong'), id='score-strength'),
                           ui.p('Display only. Stronger smoothing hides fine detail; areas and exports use raw predictions.'),
                           ui.div(ui.div(class_='score-ramp'),
                                  ui.div(ui.span('0% · low'), ui.span('50%'), ui.span('100% · high'), class_='score-ramp-labels'),
                                  id='score-legend'),
                           id='score-controls', hidden=True),
                    class_='map-tools'),
                    class_='map-inner'), class_='map-shell'),
                ui.div(
                    ui.div(
                    ui.p('CLASSIFICATION', class_='eyebrow'), ui.h2('Scene results'),
                    ui.p('Estimated area · selected model', class_='panel-subtitle'),
                    ui.input_radio_buttons('model', 'Choose a model',
                                           choices={'rf': 'Random forest', 'unet': 'U-Net', 'svm': 'SVM'}, selected='rf',
                                           inline=True),
                    ui.input_task_button('run', ui.span('Classify scene', ui.span(ui.tags.img(src='blue/arrow-white.svg', alt=''), class_='action-well'), class_='action-label'),
                                         label_busy='Classifying…', class_='run-button', width='100%'),
                    ui.div(class_row('Visible plume', 'plume', 'plume_area'),
                           class_row('Normal water', 'water', 'water_area'),
                           class_row('Land', 'land', 'land_area'), class_='class-list'),
                    ui.div(ui.h3('Antecedent rainfall near the uploaded scene'),
                           ui.div(ui.output_ui('rainfall_content'), role='status', aria_live='polite'),
                           ui.p(ui.tags.a('Open-Meteo historical weather data',
                                          href='https://open-meteo.com/en/docs/historical-weather-api',
                                          target='_blank', rel='noopener'), ' · ',
                                ui.tags.a('CC BY 4.0', href='https://creativecommons.org/licenses/by/4.0/',
                                          target='_blank', rel='noopener'), class_='rainfall-source'),
                           id='rainfall-section', class_='rainfall-block'),
                    ui.div(ui.span('DISPLAY FILTER', class_='eyebrow'),
                           ui.input_slider('threshold', 'Minimum predicted-class score', min=0, max=95,
                                           value=70, step=5, post='%'),
                           ui.p('Filters class views and area totals only. Plume-score and disagreement views retain all valid pixels. Scores are uncalibrated and cannot be compared between models.',
                                class_='score-note'), class_='threshold-block'),
                    ui.div(ui.strong('For visual review'),
                           ui.p('Mapped areas are estimates for review, not measured sediment concentration.'),
                           class_='interpretation-note'),
                    ui.div(ui.download_button('download', ui.span('Export selected model', ui.span(ui.tags.img(src='blue/arrow-blue.svg', alt=''), class_='action-well'), class_='action-label'),
                                              class_='export-button'), id='export-actions',
                           class_='export-disabled', inert=True),
                    class_='inspector-inner'), class_='inspector-shell'),
                class_='review-grid'),
            ui.tags.details(ui.tags.summary('Scene and model details'),
                            ui.tags.pre(id='scene-model-details'), class_='scene-metadata'),
            ui.p(ui.output_text('status', inline=True), role='status', aria_live='polite', class_='status-line'),
            class_='main-content'), class_='app-shell'),
    title='PlumeWatch · Three-model review', lang='en')


def server(input, output, session):
    temp = tempfile.TemporaryDirectory(prefix='plumewatch-')
    scene = reactive.value(None)
    results = reactive.value(None)
    message = reactive.value('Loading the Wellington example…')
    rainfall = reactive.value({'message': 'Open a scene and enter its Sentinel-2 acquisition date.'})
    rainfall_key = reactive.value(None)
    rainfall_cache = {}  # Successful results only, bounded and private to this session.
    future = None
    initialized = False

    def cleanup():
        retrieve_rainfall.cancel()
        if future and not future.done():
            future.add_done_callback(lambda _: temp.cleanup())
        else:
            temp.cleanup()
    session.on_ended(cleanup)

    @reactive.extended_task
    async def retrieve_rainfall(key):
        lat, lon, observed = key
        try:
            value = await asyncio.to_thread(fetch_rainfall, (lat, lon), observed)
            return {'key': key, 'data': value}
        except RainfallError as error:
            return {'key': key, 'message': 'Rainfall data unavailable for this scene/date. ' + str(error)}
        except Exception:
            return {'key': key, 'message': 'Rainfall data unavailable for this scene/date. Try again later.'}

    def request_rainfall(value, *, retry=False):
        retrieve_rainfall.cancel()
        rainfall_key.set(None)
        if value is None:
            rainfall.set({'message': 'Open a scene and enter its Sentinel-2 acquisition date.'})
            return
        try:
            observed = acquisition_date(value.get('acquisition_date'))
            lat, lon = valid_location(value.get('rainfall_location'))
        except RainfallError as error:
            rainfall.set({'message': str(error)})
            return
        key = (lat, lon, observed)
        rainfall_key.set(key)
        if key in rainfall_cache and not retry:
            rainfall.set({'data': rainfall_cache[key]})
            return
        rainfall.set({'message': 'Loading historical rainfall from Open-Meteo…'})
        retrieve_rainfall(key)

    @reactive.effect
    def rainfall_for_scene():
        request_rainfall(scene())

    @reactive.effect
    def show_rainfall():
        if retrieve_rainfall.status() != 'success':
            return
        value = retrieve_rainfall.result()
        with reactive.isolate():
            if value['key'] != rainfall_key():
                return  # Never display a response belonging to an earlier scene/date.
        if 'data' in value:
            if len(rainfall_cache) >= 32:
                rainfall_cache.pop(next(iter(rainfall_cache)))
            rainfall_cache[value['key']] = value['data']
        rainfall.set(value)

    @reactive.effect
    @reactive.event(input.retry_rainfall, ignore_init=True)
    def retry_rainfall():
        request_rainfall(scene(), retry=True)

    @reactive.effect
    @reactive.event(input.acquisition_date, ignore_none=False)
    def date_changed():
        value = scene()
        if value is not None:
            scene.set({**value, 'acquisition_date': entered_date()})

    def entered_date():
        try:
            return input.acquisition_date()
        except (TypeError, ValueError):
            return 'invalid'  # A malformed client value must clear older rainfall too.

    @reactive.extended_task
    async def load(path, name):
        nonlocal future
        def prepare():
            if Path(path).stat().st_size > MAX_BYTES:
                raise ValueError('Maximum upload size is 250 MB.')
            target = Path(temp.name) / 'input.tif'
            shutil.copyfile(path, target)
            value = prepare_scene(target)
            value['name'] = name
            return value
        future = POOL.submit(prepare)
        try:
            return await asyncio.wrap_future(future)
        except Exception as error:
            return {'error': str(error)}

    @ui.bind_task_button(button_id='run')
    @reactive.extended_task
    async def run_models(snapshot, choice):
        nonlocal future
        def work():
            root = Path(temp.name) / 'results'
            if choice == 'svm':
                return {'svm': classify_svm(snapshot, root / 'svm')}
            rf = classify_rf(snapshot, root / 'rf')
            unet = classify_unet(snapshot, root / 'unet')
            return {'rf': rf, 'unet': unet}
        future = POOL.submit(work)
        try:
            return await asyncio.wrap_future(future)
        except Exception as error:
            return {'error': str(error)}

    def busy():
        return load.status() == 'running' or run_models.status() == 'running'

    def start_load(path, name, observed=''):
        if busy():
            ui.notification_show('Wait for the current scene operation to finish.', type='message')
            return
        scene.set(None)
        results.set(None)
        ui.update_date('acquisition_date', value=observed)
        message.set('Checking the scene and preparing the map…')
        load(path, name)

    @reactive.effect
    def initial_example():
        nonlocal initialized
        if initialized:
            return
        initialized = True
        if EXAMPLE.exists():
            start_load(EXAMPLE, 'Wellington Harbour · 23 Jul 2021', '2021-07-23')
        else:
            message.set('Open a supported PlumeWatch GEE scene export to begin.')

    @reactive.effect
    @reactive.event(input.example)
    def example():
        if EXAMPLE.exists():
            start_load(EXAMPLE, 'Wellington Harbour · 23 Jul 2021', '2021-07-23')

    @reactive.effect
    @reactive.event(input.upload)
    def uploaded():
        files = input.upload()
        if files:
            start_load(files[0]['datapath'], files[0]['name'])

    @reactive.effect
    async def show_loaded():
        if load.status() != 'success':
            return
        value = load.result()
        if 'error' in value:
            message.set('Could not open scene: ' + value['error'])
            await session.send_custom_message('pw-clear', {})
            return
        with reactive.isolate():
            value['acquisition_date'] = entered_date()
        scene.set(value)
        message.set('Scene ready. Run RF / U-Net together, or select SVM to run it separately.')
        await session.send_custom_message('pw-scene', {**value['map'], 'name': value['name'],
            'sourceCrs': value['crs'], 'sourceWidth': value['width'], 'sourceHeight': value['height'],
            'bands': ['B2','B3','B4','B5','B6','B7','B8','B8A','B11','B12'],
            'sourceTags': value['source_tags']})

    @reactive.effect
    @reactive.event(input.run)
    def predict():
        if busy() or scene() is None:
            ui.update_task_button('run', state='ready')
            return
        message.set('Running SVM on the full-resolution scene; this can take several minutes…' if input.model() == 'svm'
                    else 'Running Random Forest, then U-Net on the full-resolution scene…')
        run_models(scene(), input.model())

    @reactive.effect
    async def show_prediction():
        if run_models.status() != 'success':
            return
        value = run_models.result()
        if 'error' in value:
            message.set('Classification failed: ' + value['error'])
            return
        with reactive.isolate():
            merged = {**(results() or {}), **value}
        results.set(merged)
        message.set('Classification ready. Select a model to inspect it; run SVM separately if needed.')
        await session.send_custom_message('pw-result', {key: item['map'] for key, item in merged.items()})

    @reactive.effect
    async def display_settings():
        await session.send_custom_message('pw-style', {'model': input.model(),
            'threshold': input.threshold(), 'opacity': .58})

    @reactive.effect
    async def controls():
        await session.send_custom_message('pw-controls', {'busy': busy(), 'ready': scene() is not None,
                                                           'download': selected() is not None})

    @reactive.calc
    def selected():
        current = results()
        return current.get(input.model()) if current else None

    @reactive.calc
    def stats():
        return summary(selected(), input.threshold() / 100) if selected() else None

    @render.text
    def scene_name():
        return scene()['name'] if scene() else 'River mouth / Wellington Harbour'

    @render.text
    def map_title():
        return scene()['name'].upper() if scene() else 'COASTAL SCENE / WELLINGTON HARBOUR'

    @render.text
    def scene_details():
        value = scene()
        return (f"{value['width']:,} × {value['height']:,} pixels · 10 m · {value['crs']}" if value
                else 'Single acquisition · 10 reflectance bands · example loads automatically')

    @render.text
    def status():
        value = message()
        return '' if value.startswith('Scene ready.') else value

    @render.text
    def plume_area():
        return f"{stats()['visible_plume_km2']:.2f} km²" if stats() else '—'

    @render.text
    def water_area():
        return f"{stats()['normal_water_km2']:.2f} km²" if stats() else '—'

    @render.text
    def land_area():
        return f"{stats()['land_km2']:.2f} km²" if stats() else '—'

    @render.ui
    def rainfall_content():
        value = rainfall()
        if 'data' not in value:
            return ui.div(ui.p(value['message'], class_='rainfall-note'),
                          ui.input_action_button('retry_rainfall', 'Retry rainfall',
                                                 class_='rainfall-retry') if 'key' in value else None)
        data = value['data']
        return ui.div(
            ui.tags.table(
                ui.tags.thead(ui.tags.tr(ui.tags.th('Period', scope='col'), ui.tags.th('Rainfall', scope='col'))),
                ui.tags.tbody(*[ui.tags.tr(ui.tags.th(f'Previous {n} day' + ('s' if n > 1 else ''), scope='row'),
                                           ui.tags.td(f"{data['totals_mm'][n]:.1f} mm")) for n in (1, 3, 7)]),
                class_='rainfall-table'),
            ui.p(f"Before {data['acquisition_date']} · {data['timezone']}. "
                 f"7-day window: {data['start_date']} to {data['end_date']}.", class_='rainfall-note'),
            ui.p('Estimated precipitation near the raster centre, including rain and snow. '
                 'Environmental context; not a plume rain-gauge measurement.', class_='rainfall-note'))

    @render.text
    def disagreement():
        value = results()
        other = value.get('svm' if input.model() == 'svm' else 'unet') if value else None
        return f"{disagreement_km2(value['rf'], other):.2f} km² vs RF" if value and 'rf' in value and other else '—'

    @render.download_button(filename='plumewatch_selected_model.zip')
    def download():
        value = selected()
        if value is None:
            raise ValueError('Classify a scene first.')
        return str(make_download(value, input.threshold() / 100))

    @reactive.effect
    @reactive.event(input.model_notes)
    def model_notes_handler():
        if input.model_notes():
            ui.modal_show(ui.modal(
                ui.p('RF v2, the final LayerNorm U-Net and the RBF SVM use ten Sentinel-2 bands and map normal water (0), visible plume (1), and land (3).'),
                ui.p('The SVM uses saved StandardScaler preprocessing and native SVC class predictions. Its displayed score belongs to that predicted class; it need not be the highest probability. All 49 reviewed frames contributed balanced pixel samples. No independent SVM accuracy has been established.'),
                ui.p('The U-Net was trained on all 49 reviewed frames and has no independent accuracy score. RF v2 held-out scores describe reference-annotation agreement, not physical sediment accuracy. Scene appearance alone cannot determine which model is more accurate.'),
                ui.p('Excluded pixels are 255. The score control hides low predicted-class scores in the preview; downloads retain raw class IDs and separate scores. Footprint areas remain estimates for review.'),
                title='Model and interpretation notes', easy_close=True,
                footer=ui.modal_button('Close')))

app = App(app_ui, server, static_assets=ROOT / 'www')
