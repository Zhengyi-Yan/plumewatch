"""Run: shiny run --reload app.py"""
import asyncio
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from shiny import App, reactive, render, ui
from processing import EXAMPLE, MAX_BYTES, prepare_scene, classify, summary, make_download

ROOT=Path(__file__).resolve().parent
POOL=ThreadPoolExecutor(max_workers=2)

def metric(label,value_id,unit='km²'):
    return ui.div(ui.span(label,class_='metric-label'),ui.div(ui.output_text(value_id,inline=True),ui.span(unit,class_='unit'),class_='metric-value'),class_='metric')

app_ui=ui.page_fluid(
    ui.tags.head(ui.tags.meta(name='viewport',content='width=device-width, initial-scale=1'),
                 ui.tags.link(rel='stylesheet',href='leaflet.css'),ui.tags.link(rel='stylesheet',href='app.css'),
                 ui.tags.script(src='leaflet.js'),ui.tags.script(src='app.js',defer=True)),
    ui.div(
        ui.tags.header(ui.div(ui.span('P',class_='brand-mark'),ui.span('PlumeWatch'),class_='brand'),
                       ui.div(ui.span('Coastal image workspace',class_='header-context'),
                              ui.input_action_button('about','Model details',class_='quiet-button'),class_='header-right'),class_='glass app-header'),
        ui.div(
            ui.tags.aside(
                ui.div(ui.span('01',class_='section-number'),ui.h2('Image'),class_='section-heading'),
                ui.input_file('upload',None,accept=['.tif','.tiff'],button_label='Open GeoTIFF',placeholder='GEE scene export'),
                ui.input_action_button('example','Load Wellington example',class_='example-button'),
                ui.div(ui.output_text('scene_name'),class_='scene-name'),ui.div(ui.output_text('scene_details'),class_='scene-details'),
                ui.div(class_='divider'),
                ui.div(ui.span('02',class_='section-number'),ui.h2('Classification'),class_='section-heading'),
                ui.p('Hutt pilot',class_='model-label'),ui.p('Normal water and plume. Multiclass model pending.',class_='muted'),
                ui.input_task_button('run','Classify image',label_busy='Classifying…',class_='run-button',width='100%'),
                ui.div(class_='divider'),
                ui.div(ui.span('03',class_='section-number'),ui.h2('Display'),class_='section-heading'),
                ui.input_checkbox_group('layers',None,choices={'1':'Plume class','0':'Normal-water class','uncertain':'Uncertain'},selected=['1','uncertain']),
                ui.input_slider('opacity','Overlay opacity',min=0,max=100,value=45,post='%'),
                ui.input_slider('threshold','Minimum model score',min=50,max=95,value=70,step=5,post='%'),
                ui.p('Low-score pixels appear as uncertain. This is not an area error margin.',class_='muted'),
                ui.div(class_='divider'),
                ui.div(ui.download_button('download','Download results',class_='download-button'),id='export-actions',class_='export-disabled',inert=True),
                ui.p('Classification + scores + summary',class_='download-caption'),
                class_='glass sidebar'),
            ui.tags.main(
                ui.div(ui.div(ui.span('PLUMEWATCH',class_='eyebrow'),ui.h1('Scene workspace')),ui.span('Sentinel-2',class_='source-label'),class_='workspace-heading'),
                ui.div(
                    ui.div(ui.div(ui.tags.button('Original',type='button',data_view='original'),
                                  ui.tags.button('Overlay',type='button',data_view='overlay',aria_pressed='true'),
                                  ui.tags.button('Classes',type='button',data_view='classes'),class_='view-switch'),
                           ui.tags.button('Fit scene',type='button',id='fit-scene',class_='fit-button'),class_='glass map-toolbar'),
                    ui.div(id='map',role='region',aria_label='Satellite scene map'),
                    ui.div(ui.span('Loading example…',id='map-caption'),class_='glass map-caption'),
                    ui.div(id='pixel-info',class_='glass pixel-info',hidden=True),class_='map-stage'),
                ui.div(metric('Predicted plume class','plume_area'),metric('Analysed coverage','analysed_area'),metric('Uncertain','uncertain_area'),class_='glass metrics'),
                ui.div(ui.output_text('status'),role='status',aria_live='polite',class_='status-line'),
                ui.p('Pilot results include land: no water mask is applied. Area values are provisional class footprints.',class_='pilot-note'),
                class_='workspace'),class_='app-layout'),
        ui.tags.footer(ui.span('GISCI 341'),ui.span('Local processing · files stay in this session'),class_='app-footer'),
        class_='app-shell'),
    title='PlumeWatch',lang='en')

def server(input,output,session):
    temp=tempfile.TemporaryDirectory(prefix='plumewatch-')
    scene=reactive.value(None); result=reactive.value(None); message=reactive.value('Loading the Wellington example…')
    future=None

    def cleanup():
        if future and not future.done(): future.add_done_callback(lambda _:temp.cleanup())
        else: temp.cleanup()
    session.on_ended(cleanup)

    @reactive.extended_task
    async def load(path,name):
        nonlocal future
        def prepare():
            if Path(path).stat().st_size>MAX_BYTES: raise ValueError('Maximum upload size is 250 MB.')
            copied=Path(temp.name)/'input.tif'
            shutil.copyfile(path,copied)
            value=prepare_scene(copied);value['name']=name
            return value
        future=POOL.submit(prepare)
        try: return await asyncio.wrap_future(future)
        except Exception as error: return {'error':str(error)}

    @ui.bind_task_button(button_id='run')
    @reactive.extended_task
    async def run_model(snapshot):
        nonlocal future
        future=POOL.submit(classify,snapshot,Path(temp.name)/'results')
        try: return await asyncio.wrap_future(future)
        except Exception as error: return {'error':str(error)}

    def busy(): return load.status()=='running' or run_model.status()=='running'

    def start_load(path,name):
        if busy():
            ui.notification_show('Please wait for the current image operation to finish.',type='message');return
        scene.set(None);result.set(None);message.set('Checking image and preparing the map…')
        load(path,name)

    @reactive.effect
    @reactive.event(input.example,ignore_none=False)
    def example():
        if EXAMPLE.exists(): start_load(EXAMPLE,'Wellington Harbour · 23 Jul 2021 NZ')
        else: message.set('Open a PlumeWatch GEE scene export to begin.')

    @reactive.effect
    @reactive.event(input.upload)
    def uploaded():
        files=input.upload()
        if files: start_load(files[0]['datapath'],files[0]['name'])

    @reactive.effect
    async def show_loaded():
        if load.status()!='success': return
        value=load.result()
        if 'error' in value:
            message.set('Could not open image: '+value['error']);await session.send_custom_message('pw-clear',{});return
        scene.set(value);message.set('Image ready. Run classification to explore the model output.')
        await session.send_custom_message('pw-scene',value['map'])

    @reactive.effect
    @reactive.event(input.run)
    def predict():
        if busy() or scene() is None:
            ui.update_task_button('run',state='ready');return
        result.set(None);message.set('Classifying the full-resolution image…')
        run_model(scene())

    @reactive.effect
    async def show_prediction():
        if run_model.status()!='success': return
        value=run_model.result()
        if 'error' in value: message.set('Classification failed: '+value['error']);return
        result.set(value);message.set('Classification complete. Display controls do not rerun the model.')
        await session.send_custom_message('pw-result',value['map'])

    @reactive.effect
    async def display_settings():
        await session.send_custom_message('pw-style',{'layers':input.layers(),'opacity':input.opacity()/100,'threshold':input.threshold()})

    @reactive.effect
    async def controls():
        await session.send_custom_message('pw-controls',{'busy':busy(),'ready':scene() is not None,'download':result() is not None})

    @render.text
    def scene_name(): return scene()['name'] if scene() else 'No image selected'
    @render.text
    def scene_details():
        s=scene()
        return f"{s['width']:,} × {s['height']:,} pixels · 10 m · {s['crs']}" if s else '12-band GEE GeoTIFF · up to 250 MB'
    @render.text
    def status(): return message()

    @reactive.calc
    def stats(): return summary(result(),input.threshold()/100) if result() else None
    @render.text
    def plume_area(): return f"{stats()['predicted_plume_class_km2']:.2f}" if stats() else '—'
    @render.text
    def analysed_area(): return f"{stats()['analysed_km2']:.2f}" if stats() else '—'
    @render.text
    def uncertain_area(): return f"{stats()['uncertain_km2']:.2f}" if stats() else '—'

    @render.download_button(filename='plumewatch_results.zip')
    def download():
        if result() is None: raise ValueError('Classify an image first.')
        return str(make_download(result(),input.threshold()/100))

    @reactive.effect
    @reactive.event(input.about)
    def about():
        ui.modal_show(ui.modal(ui.p('This dashboard currently uses the original two-class Random Forest trained on the Hutt scene.'),
            ui.p('It predicts normal water and plume. It has no land/shallow-water classes yet and no water mask; some land is predicted as plume.'),
            ui.p('The model score is the forest’s class score, not a calibrated confidence interval. The area strip counts native 10 m pixels above your score threshold.'),
            ui.p('Downloads contain raw class IDs, winning-class scores, and a threshold-specific summary. The map is a smaller preview; area is calculated on the original grid.'),
            title='Model details',easy_close=True,footer=ui.modal_button('Close')))

app=App(app_ui,server,static_assets=ROOT/'www')
