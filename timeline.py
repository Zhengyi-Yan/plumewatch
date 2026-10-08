"""Isolated multi-acquisition prototype, mounted at /timeline/."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import uuid
from shiny import App, reactive, render, ui
from time_series import inspect_files, build_series, export_series
from rainfall import MIN_ACQUISITION_DATE, fetch_rainfall, acquisition_date

ROOT=Path(__file__).resolve().parent
# ponytail: one worker bounds batch inference memory; add a job service for hosted multi-user use.
POOL=ThreadPoolExecutor(max_workers=1)
LOCAL_ARNO=[ROOT/f'data/raw/spencer-sentinel-2/Italy_Arno_{date}_S2_L2A_12band.tif' for date in ('20200226','20200228','20200304')]


def card(*children, class_=''):
    return ui.div(ui.div(*children,class_='series-card-inner'),class_='series-card '+class_)


app_ui=ui.page_fluid(
    ui.tags.head(ui.tags.meta(name='viewport',content='width=device-width, initial-scale=1'),
        ui.tags.link(rel='stylesheet',href='https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap'),
        ui.tags.link(rel='stylesheet',href='leaflet.css'),
        ui.tags.link(rel='stylesheet',href='app.css?v=20261008-series'),
        ui.tags.link(rel='stylesheet',href='timeline.css?v=20261009-series1'),
        ui.tags.script(src='leaflet.js'),ui.tags.script(src='timeline.js?v=20261009-series1',defer=True)),
    ui.div(ui.tags.aside(
        ui.div(ui.span('plumewatch',class_='brand-word'),class_='brand'),
        ui.p('SATELLITE INSIGHT STUDIO',class_='brand-caption'),ui.div(class_='nav-rule'),
        ui.p('WORKSPACE',class_='nav-label'),
        ui.tags.nav(ui.tags.a(ui.tags.img(src='blue/overview.svg',alt='',class_='nav-icon'),'Classification',href='/',class_='nav-link'),
                    ui.tags.a(ui.tags.img(src='blue/scenes.svg',alt='',class_='nav-icon'),'Time series',href='/timeline/',class_='nav-link active'),
                    class_='side-nav'),class_='site-sidebar'),
    ui.tags.main(
        ui.div(ui.p('COASTAL MONITORING / TIME SERIES',class_='eyebrow'),
               ui.h1('Compare plume extent over time.'),
               ui.p('Classify Sentinel-2 images from different dates, compare plume extent, and view preceding rainfall.',class_='intro'),
               class_='series-hero'),
        ui.div(card(
            ui.div(ui.span('01',class_='series-step'),ui.div(ui.h2('Build your observation series'),
                ui.p('2–6 images · one location · distinct dates',class_='series-muted')),class_='series-section-title'),
            ui.div(ui.input_file('series_upload',None,multiple=True,accept=['.tif','.tiff'],button_label='Choose images',placeholder='12-band Sentinel-2 GeoTIFFs'),
                ui.p('Same projected CRS; shared coverage required. Up to 250 MiB per file and 20 million source pixels per batch.',class_='series-muted'),class_='series-upload'),
            ui.input_action_button('series_example','Load local Arno sequence',class_='example-button') if all(p.is_file() for p in LOCAL_ARNO) else None,
            ui.output_ui('series_files'),
            ui.input_checkbox('series_confirm','I have checked every acquisition date.',value=False),
            ui.div(ui.input_select('series_model','Model for every date',choices={'rf':'Random Forest','unet':'U-Net','svm':'SVM'},selected='rf'),
                   ui.input_numeric('series_threshold','Minimum predicted-class score (%)',value=0,min=0,max=95,step=5),class_='series-settings'),
            ui.p('0% keeps every predicted plume pixel. One fixed filter applies to all dates; scores are uncalibrated.',class_='series-muted'),
            ui.input_task_button('series_run','Classify series ↗',label_busy='Processing series…',class_='run-button',width='100%'),
            ui.div(ui.output_text('series_status'),role='status',aria_live='polite',class_='series-status'),
            class_='series-setup'),class_='series-intake'),
        ui.div(
            ui.div(ui.div(ui.p('YOUR UPLOADED IMAGES',class_='eyebrow'),ui.h2('Browse the dates'),
                       ui.p('Choose an image to view it beside the reference date.',class_='series-muted')),class_='series-result-heading'),
            ui.div(id='series-observations',class_='series-observations'),
            ui.div(card(ui.h3('Plume area by date'),ui.p('Predicted plume area on the same comparable ground.',class_='series-muted'),
                        ui.div(id='series-area-chart',class_='series-chart')),
                   card(ui.h3('Rainfall before each image'),ui.p('Total rainfall in the 7 days before capture.',class_='series-muted'),
                        ui.div(id='series-rain-chart',class_='series-chart'),
                        ui.div(ui.p(ui.tags.a('Open-Meteo',href='https://open-meteo.com/en/docs/historical-weather-api',target='_blank',rel='noopener'),' · ',
                             ui.tags.a('CC BY 4.0',href='https://creativecommons.org/licenses/by/4.0/',target='_blank',rel='noopener'),class_='series-muted'),
                        ui.input_action_button('series_retry_weather','Retry missing rainfall',class_='example-button'),class_='series-weather-footer')),
                   class_='series-charts'),
            ui.div(ui.div(ui.p('IMAGE COMPARISON',class_='eyebrow'),ui.h2('See what changed'),
                       ui.p('Keep a reference image on the left. Browse or play the dates on the right.',class_='series-muted')),
                   ui.tags.label(ui.tags.input(type='checkbox',id='series-show-plume',checked=True),ui.span(class_='series-plume-dot'),' Show plume'),
                   class_='series-result-heading',id='series-comparison-heading'),
            ui.div(card(ui.div(ui.tags.label('Reference image',**{'for':'series-left-date'}),ui.tags.select(id='series-left-date'),class_='series-map-heading'),
                        ui.p('Fixed baseline · maps share centre and zoom',class_='series-map-note'),
                        ui.div(id='series-left-map',class_='series-map'),class_='series-reference'),
                   card(ui.div(ui.tags.label('Viewing image',**{'for':'series-right-date'}),ui.tags.select(id='series-right-date'),
                               ui.tags.button('Play dates',id='series-play',type='button'),class_='series-map-heading'),
                        ui.p('Browse acquisitions or play the sequence',class_='series-map-note'),
                        ui.div(id='series-right-map',class_='series-map'),class_='series-viewing'),
                   class_='series-maps'),
            ui.div(ui.p('Playback changes only the viewing image. The change comparison stays fixed.',class_='series-muted'),
                   ui.tags.button('Compare these dates',id='series-compare',type='button',class_='series-compare-button'),
                   class_='series-compare-actions'),
            ui.p(id='series-compare-feedback',role='status',class_='series-muted'),
            ui.tags.details(
                ui.tags.summary(ui.span('Where did the plume change?'),ui.span('Map comparison',class_='series-muted')),
                card(ui.div(ui.div(ui.p('PREDICTED CHANGE',class_='eyebrow'),ui.h3(id='series-change-title')),
                                 ui.p(id='series-change-description',class_='series-muted'),class_='series-analysis-heading'),
                     ui.div(ui.tags.label('Show',**{'for':'series-footprint-mode'}),
                            ui.tags.select(ui.tags.option('Change between the compared dates',value='pair'),ui.tags.option('Plume across all uploaded dates',value='frequency'),id='series-footprint-mode'),class_='series-map-heading'),
                     ui.p(id='series-change-instructions',class_='series-muted'),
                     ui.div(class_='series-layer-cards',id='series-footprint-legend'),
                     ui.div(id='series-change-map',class_='series-map series-change-map'),
                     ui.p('Colour shows classification differences, not measured sediment movement. Uncoloured areas can include invalid coverage.',class_='series-muted series-map-footnote')),
                id='series-change-section',class_='series-disclosure'),
            ui.tags.details(ui.tags.summary('Data, comparison coverage & export'),
                card(ui.p(id='series-coverage-note',class_='series-muted'),ui.h3('Observation details'),ui.div(id='series-table'),
                     ui.p('Rainfall is context, not evidence of causation. Seven-day windows can overlap. Areas are model estimates; tides, visibility and model errors can affect change.',class_='series-muted'),
                     ui.download_button('series_download','Export time series',class_='export-button')),
                class_='series-disclosure'),
            id='series-results',hidden=True),
        class_='main-content series-page'),class_='app-shell'),title='PlumeWatch · Time series',lang='en')


def server(input,output,session):
    temp=tempfile.TemporaryDirectory(prefix='plumewatch-series-')
    entries=reactive.value([]); result=reactive.value(None)
    message=reactive.value('Choose at least two images to begin.')
    future=None
    def cleanup():
        if future and not future.done(): future.add_done_callback(lambda _:temp.cleanup())
        else: temp.cleanup()
    session.on_ended(cleanup)
    @reactive.extended_task
    async def load(files):
        nonlocal future
        future=POOL.submit(inspect_files,files,Path(temp.name)/uuid.uuid4().hex)
        try: return {'entries':await asyncio.wrap_future(future)}
        except Exception as error: return {'error':str(error)}
    @reactive.effect
    @reactive.event(input.series_upload)
    def uploaded():
        if busy(): return
        files=input.series_upload()
        entries.set([]); result.set(None); ui.update_checkbox('series_confirm',value=False)
        if files:
            message.set('Checking imagery and shared coverage…'); load(files)
    @reactive.effect
    @reactive.event(input.series_example)
    def example():
        if busy() or not all(p.is_file() for p in LOCAL_ARNO): return
        entries.set([]); result.set(None); ui.update_checkbox('series_confirm',value=False)
        message.set('Checking the local Arno acquisitions…')
        load([{'name':p.name,'datapath':str(p)} for p in LOCAL_ARNO])
    @reactive.effect
    async def loaded():
        if load.status()!='success': return
        value=load.result()
        if 'error' in value: message.set(value['error']); return
        entries.set(value['entries']); message.set('Check acquisition dates, then classify the series.')
    @render.ui
    def series_files():
        return ui.div(*[ui.div(ui.div(ui.strong(e['name']),ui.span('Date suggested from filename; please verify.' if e['date'] else 'Enter the actual capture date.',class_='series-muted')),
                      ui.input_date(f'series_date_{i}',f'Acquisition {i+1}',value=e['date'] or None,min=MIN_ACQUISITION_DATE),class_='series-file-row') for i,e in enumerate(entries())],class_='series-file-list')
    @ui.bind_task_button(button_id='series_run')
    @reactive.extended_task
    async def run(snapshot,model,threshold):
        nonlocal future
        loop=asyncio.get_running_loop(); queue=asyncio.Queue()
        def progress(text): loop.call_soon_threadsafe(queue.put_nowait,text)
        folder=Path(temp.name)/uuid.uuid4().hex
        future=POOL.submit(build_series,snapshot,model,threshold,folder,progress=progress)
        wrapped=asyncio.wrap_future(future)
        while not wrapped.done():
            try:
                text=await asyncio.wait_for(queue.get(),timeout=.25)
                await session.send_custom_message('series-progress',text)
            except asyncio.TimeoutError: pass
        try: return {'result':await wrapped}
        except Exception as error: return {'error':str(error)}
    def busy(): return load.status()=='running' or run.status()=='running' or retry_weather.status()=='running'
    @reactive.effect
    @reactive.event(input.series_run)
    def classify():
        if busy(): return
        try:
            if not input.series_confirm(): raise ValueError('Confirm that every acquisition date is correct.')
            snapshot=[{**e,'date':acquisition_date(input[f'series_date_{i}']()).isoformat()} for i,e in enumerate(entries())]
            if len(snapshot)<2: raise ValueError('Choose at least two images.')
            threshold=float(input.series_threshold())/100
            if not 0<=threshold<=.95: raise ValueError('Score filter must be between 0 and 95%.')
            if len({e['date'] for e in snapshot})!=len(snapshot): raise ValueError('Choose distinct dates; merge tiles from one acquisition before upload.')
        except (ValueError,TypeError) as error:
            message.set(str(error)); ui.update_task_button('series_run',state='ready'); return
        result.set(None); message.set('Starting sequential classification…')
        run(snapshot,input.series_model(),threshold)
    @reactive.effect
    async def completed():
        if run.status()!='success': return
        value=run.result()
        if 'error' in value: message.set('Could not build series: '+value['error']); return
        result.set(value['result']); message.set('Series ready. Explore observations below.')
    @reactive.extended_task
    async def retry_weather(snapshot):
        nonlocal future
        def work():
            value={**snapshot,'rows':[dict(r) for r in snapshot['rows']]}
            for row in value['rows']:
                if row['weather'] is not None: continue
                try:
                    row['weather']=fetch_rainfall(value['location'],row['date'])
                    row['rainfall_7d_mm']=row['weather']['totals_mm'][7]; row['weather_error']=''
                except Exception as error: row['weather_error']=str(error)
            return value
        future=POOL.submit(work)
        return await asyncio.wrap_future(future)
    @reactive.effect
    @reactive.event(input.series_retry_weather)
    def retry():
        if not busy() and result(): message.set('Retrying unavailable rainfall…'); retry_weather(result())
    @reactive.effect
    def retried():
        if retry_weather.status()=='success': result.set(retry_weather.result()); message.set('Rainfall refresh complete.')
    @reactive.effect
    async def publish():
        value=result()
        await session.send_custom_message('series-result',None if value is None else {k:v for k,v in value.items() if k!='folder'})
    @reactive.effect
    async def controls():
        await session.send_custom_message('series-controls',{'busy':busy(),'ready':bool(entries())})
    @render.text
    def series_status(): return message()
    @render.download_button(filename='plumewatch_time_series.zip')
    def series_download():
        if not result(): raise ValueError('Build a series first.')
        return str(export_series(result()))

app=App(app_ui,server,static_assets=ROOT/'www')
