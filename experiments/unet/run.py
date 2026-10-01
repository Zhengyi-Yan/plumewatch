"""Four held-out-group U-Net folds, native-grid predictions, and RF comparison."""

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio
import torch
from rasterio.windows import Window
from sklearn.metrics import confusion_matrix

from data import (ROOT, PATCH, PatchSampler, class_weights, fit_normalization,
                  load_scenes, normalized_input, rf_eval_indices)
from model import UNet
from train_multiclass import CLASS_IDS, scores
from render_rf_examples import EXAMPLES

HERE = Path(__file__).resolve().parent
OUT = HERE / 'outputs'
SEED = 42
EPOCHS = 40
PATCHES_PER_EPOCH = 128
BATCH = 4
LEARNING_RATE = 3e-4
WEIGHT_DECAY = 1e-4
STRIDE = 192
VALUES = np.array(CLASS_IDS, dtype='uint8')
EXAMPLE_NAMES = {name for _, name in EXAMPLES}


def require_mps():
    if not torch.backends.mps.is_available():
        raise RuntimeError('PyTorch MPS is unavailable; refusing a long CPU training run')
    return torch.device('mps')


def train_fold(scenes, held_out, device, epochs=EPOCHS, batches=PATCHES_PER_EPOCH // BATCH):
    index = int(held_out.rsplit('_', 1)[-1])
    torch.manual_seed(SEED + index)
    np.random.seed(SEED + index)
    mean, std = fit_normalization(scenes, held_out)
    weights = class_weights(scenes, held_out)
    sampler = PatchSampler(scenes, held_out, mean, std, SEED + index)
    model = UNet().to(device)
    criterion = torch.nn.CrossEntropyLoss(weight=torch.tensor(weights, device=device), ignore_index=255)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    losses = []
    try:
        for epoch in range(epochs):
            model.train()
            running = 0.0
            for _ in range(batches):
                images, labels = sampler.batch(BATCH)
                images = torch.from_numpy(images).to(device)
                labels = torch.from_numpy(labels).to(device)
                optimizer.zero_grad(set_to_none=True)
                loss = criterion(model(images), labels)
                if not torch.isfinite(loss):
                    raise ValueError('Non-finite training loss')
                loss.backward()
                optimizer.step()
                running += float(loss.detach().cpu())
            losses.append(running / batches)
            if (epoch + 1) % 5 == 0 or epoch == 0:
                print(f'{held_out} epoch {epoch + 1}/{epochs} loss {losses[-1]:.4f}', flush=True)
    finally:
        sampler.close()
    return model, mean, std, weights, losses


def positions(size):
    if size < PATCH:
        raise ValueError('Source image is smaller than one inference tile')
    values = list(range(0, size - PATCH + 1, STRIDE))
    if values[-1] != size - PATCH:
        values.append(size - PATCH)
    return values


def predict_scene(scene, model, mean, std, device, output=None):
    """Return a native-grid class map; save class and plume-score TIFFs if requested."""
    with rasterio.open(ROOT / scene.record['source_tif']) as src:
        height, width = src.shape
        probability_sum = np.zeros((3, height, width), dtype='float32')
        weight_sum = np.zeros((height, width), dtype='float32')
        valid_all = np.zeros((height, width), dtype=bool)
        edge = np.maximum(np.hanning(PATCH), 0.1).astype('float32')
        tile_weight = np.outer(edge, edge)
        model.eval()
        with torch.inference_mode():
            for y in positions(height):
                for x in positions(width):
                    data = src.read(window=Window(x, y, PATCH, PATCH))
                    image, valid = normalized_input(data, mean, std)
                    tensor = torch.from_numpy(image[None]).to(device)
                    probability = torch.softmax(model(tensor), dim=1)[0].cpu().numpy()
                    probability_sum[:, y:y + PATCH, x:x + PATCH] += probability * tile_weight
                    weight_sum[y:y + PATCH, x:x + PATCH] += tile_weight
                    valid_all[y:y + PATCH, x:x + PATCH] |= valid
        if not (weight_sum > 0).all():
            raise ValueError('Inference did not cover every source pixel')
        probability_sum /= weight_sum[None]
        classified = VALUES[probability_sum.argmax(axis=0)]
        classified[~valid_all] = 255
        if output is not None:
            output.mkdir(parents=True, exist_ok=True)
            stem = Path(scene.name).stem
            profile = src.profile.copy()
            profile.update(count=1, dtype='uint8', nodata=255, compress='deflate')
            with rasterio.open(output / f'{stem}_unet_class.tif', 'w', **profile) as dst:
                dst.write(classified, 1)
                dst.set_band_description(1, 'held_out_class_id')
                dst.update_tags(classes='0=normal_water;1=plume;3=land;255=invalid',
                                source_tif=scene.record['source_tif'], fold=scene.group)
            profile.update(dtype='float32', nodata=-9999)
            plume = probability_sum[1].copy()
            plume[~valid_all] = -9999
            with rasterio.open(output / f'{stem}_unet_plume_score.tif', 'w', **profile) as dst:
                dst.write(plume, 1)
                dst.set_band_description(1, 'uncalibrated_plume_softmax_score')
                dst.update_tags(source_tif=scene.record['source_tif'], fold=scene.group,
                                warning='Not calibrated probability or area uncertainty')
        return classified


def verify_reference_pixels(scene, truth, reference):
    actual = [int((truth == cls).sum()) for cls in CLASS_IDS]
    expected = [reference['classes'][name]['support'] for name in ('normal_water', 'plume', 'land')]
    if actual != expected:
        raise ValueError(f'RF/U-Net evaluation pixels differ for {scene.name}: {actual} != {expected}')


def smoke():
    device = require_mps()
    scenes = load_scenes()
    held_out = sorted({scene.group for scene in scenes})[0]
    model, mean, std, weights, losses = train_fold(scenes, held_out, device, epochs=1, batches=2)
    sampler = PatchSampler(scenes, held_out, mean, std, SEED)
    try:
        image, labels = sampler.sample()
    finally:
        sampler.close()
    with torch.inference_mode():
        probs = model(torch.from_numpy(image[None]).to(device)).softmax(1)
    if tuple(probs.shape) != (1, 3, PATCH, PATCH) or not np.isfinite(probs.cpu().numpy()).all():
        raise ValueError('Invalid smoke-test prediction')
    print('MPS smoke passed; two batches and one 256px inference patch',
          'labelled pixels', int((labels != 255).sum()), 'class weights', weights.tolist())


def run():
    device = require_mps()
    scenes = load_scenes()
    groups = sorted({scene.group for scene in scenes})
    rf = json.loads((ROOT / 'results/multiclass_rf_v1/metrics.json').read_text())
    rf_scene = {row['png']: row for fold in rf['folds'] for row in fold['scenes']}
    if set(rf_scene) != {scene.name for scene in scenes}:
        raise ValueError('RF baseline does not cover the same 21 scenes')
    output = OUT / 'predictions'
    checkpoints = OUT / 'checkpoints'
    checkpoints.mkdir(parents=True, exist_ok=True)
    folds = []
    total = np.zeros((3, 3), dtype='int64')
    for group in groups:
        model, mean, std, weights, losses = train_fold(scenes, group, device)
        path = checkpoints / f'{group}.pt'
        torch.save({'state_dict': {k: v.detach().cpu() for k, v in model.state_dict().items()},
                    'mean': mean, 'std': std, 'weights': weights, 'losses': losses,
                    'held_out_group': group, 'train_scenes': [s.name for s in scenes if s.group != group],
                    'epochs': EPOCHS, 'patches_per_epoch': PATCHES_PER_EPOCH,
                    'batch': BATCH, 'base_seed': SEED,
                    'fold_seed': SEED + int(group.rsplit('_', 1)[-1])}, path)
        fold_matrix = np.zeros((3, 3), dtype='int64')
        per_scene = []
        for scene in scenes:
            if scene.group != group:
                continue
            classified = predict_scene(scene, model, mean, std, device,
                                       output if scene.name in EXAMPLE_NAMES else None)
            ids = rf_eval_indices(scene)
            truth = scene.mask.ravel()[ids]
            verify_reference_pixels(scene, truth, rf_scene[scene.name])
            predicted = classified.ravel()[ids]
            matrix = confusion_matrix(truth, predicted, labels=CLASS_IDS)
            fold_matrix += matrix
            per_scene.append({'png': scene.name, 'rf_plume_f1': rf_scene[scene.name]['classes']['plume']['f1'],
                              **scores(matrix)})
            print(group, scene.name, 'U-Net plume F1',
                  round(per_scene[-1]['classes']['plume']['f1'], 3), flush=True)
        total += fold_matrix
        folds.append({'held_out_group': group, 'fold_seed': SEED + int(group.rsplit('_', 1)[-1]),
                      'training_scenes': [s.name for s in scenes if s.group != group],
                      'losses': losses, 'normalization': {'mean': mean.tolist(), 'std': std.tolist()},
                      'class_weights': weights.tolist(), 'scenes': per_scene, **scores(fold_matrix)})
        del model
        torch.mps.empty_cache()
    unet = scores(total)
    clear = {name for kind, name in EXAMPLES if kind == 'clear'}
    weak = {row['png'] for fold in rf['folds'] for row in fold['scenes']
            if row['classes']['plume']['f1'] < 0.7}
    rows = {row['png']: row for fold in folds for row in fold['scenes']}
    clear_drops = {name: rows[name]['classes']['plume']['f1'] - rf_scene[name]['classes']['plume']['f1']
                   for name in clear}
    weak_deltas = {name: rows[name]['classes']['plume']['f1'] - rf_scene[name]['classes']['plume']['f1']
                   for name in weak}
    report = {'method': 'four linked-site-event-held-out U-Net folds',
              'class_ids': {'normal_water': 0, 'plume': 1, 'land': 3, 'ignored': 255},
              'input_bands': ['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12'],
              'training': {'base_seed': SEED, 'epochs': EPOCHS, 'patch_size': PATCH,
                           'patches_per_epoch': PATCHES_PER_EPOCH, 'batch': BATCH,
                           'learning_rate': LEARNING_RATE, 'weight_decay': WEIGHT_DECAY,
                           'device': 'mps'},
              'unet_overall': unet, 'rf_overall': rf['overall_scene_balanced_sample'],
              'plume_f1_delta': unet['classes']['plume']['f1'] - rf['overall_scene_balanced_sample']['classes']['plume']['f1'],
              'clear_scene_plume_f1_deltas': clear_drops,
              'weak_scene_plume_f1_deltas': weak_deltas,
              'pilot_improved': (unet['classes']['plume']['f1'] > rf['overall_scene_balanced_sample']['classes']['plume']['f1']
                                 and np.mean(list(weak_deltas.values())) > 0
                                 and all(delta >= -0.05 for delta in clear_drops.values())),
              'folds': folds,
              'limitations': ['Only four independent groups; no untouched test set.',
                              'Metrics cover sparse labelled pixels, not whole-scene area.',
                              'Plume softmax score is uncalibrated and not an area error bound.',
                              'April comparison labels remain disputed and unchanged.']}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'metrics.json').write_text(json.dumps(report, indent=2) + '\n')
    from gallery import build_galleries
    build_galleries(scenes, output, OUT / 'galleries')
    print('Overall held-out plume F1: U-Net', round(unet['classes']['plume']['f1'], 3),
          'RF', round(rf['overall_scene_balanced_sample']['classes']['plume']['f1'], 3), flush=True)
    print('Report:', OUT / 'metrics.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('smoke', 'run'))
    args = parser.parse_args()
    smoke() if args.command == 'smoke' else run()
