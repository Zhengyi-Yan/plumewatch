"""Native-grid TIFF patches and the RF's exact held-out evaluation pixels."""

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from annotation_pipeline import MANIFEST, check_source  # noqa: E402
from train_multiclass import (CLASS_IDS, EVAL_PER_SCENE, SEED, groups_for,
                              mask_path, sample_scene, training_set)  # noqa: E402

PATCH = 256
VALID_SCL = (2, 4, 5, 6, 7)


@dataclass
class Scene:
    record: dict
    group: str
    mask: np.ndarray
    pixels: dict

    @property
    def name(self):
        return Path(self.record['png']).name


def load_scenes():
    records = [r for r in json.loads(MANIFEST.read_text()) if mask_path(r).exists()]
    groups = groups_for(records)
    if len(records) != 21 or len(set(groups)) != 4:
        raise ValueError('Expected the frozen 21-scene, four-group CVAT pilot')
    scenes = []
    for record, group in zip(records, groups):
        with rasterio.open(ROOT / record['source_tif']) as src, rasterio.open(mask_path(record)) as labelled:
            check_source(src, record)
            if (src.crs, src.transform, src.shape) != (labelled.crs, labelled.transform, labelled.shape):
                raise ValueError('Source/mask grid mismatch: ' + record['png'])
            mask = labelled.read(1)
        if not set(np.unique(mask)).issubset({0, 1, 3, 255}):
            raise ValueError('Unexpected class ID in ' + record['png'])
        pixels = {cls: np.flatnonzero(mask == cls).astype('int32') for cls in CLASS_IDS}
        scenes.append(Scene(record, group, mask, pixels))
    return scenes


def fit_normalization(scenes, held_out):
    """Learn scaling from balanced samples of training groups only."""
    train = [scene for scene in scenes if scene.group != held_out]
    records = [scene.record for scene in train]
    samples = [sample_scene(record) for record in records]
    groups = [scene.group for scene in train]
    x, _ = training_set(samples, groups, list(range(len(train))), np.random.default_rng(SEED))
    mean = x.mean(axis=0).astype('float32')
    std = np.maximum(x.std(axis=0), 1e-4).astype('float32')
    return mean, std


def valid_pixels(data):
    bands = data[:10]
    valid = (data[11] == 1) & np.isfinite(bands).all(axis=0)
    valid &= (bands != -9999).all(axis=0) & np.isin(data[10], VALID_SCL)
    return valid


def normalized_input(data, mean, std):
    valid = valid_pixels(data)
    image = np.clip((data[:10] - mean[:, None, None]) / std[:, None, None], -5, 5)
    image[:, ~valid] = 0
    return np.ascontiguousarray(image, dtype='float32'), valid


def class_weights(scenes, held_out):
    counts = np.array([sum(len(scene.pixels[cls]) for scene in scenes if scene.group != held_out)
                       for cls in CLASS_IDS], dtype='float64')
    if (counts == 0).any():
        raise ValueError('Training fold lacks a class')
    weights = np.sqrt(counts.mean() / counts)
    weights /= weights.mean()
    return np.clip(weights, 0.5, 3).astype('float32')


class PatchSampler:
    def __init__(self, scenes, held_out, mean, std, seed):
        self.scenes, self.mean, self.std = scenes, mean, std
        self.rng = np.random.default_rng(seed)
        self.eligible = {}
        self.sources = {}
        for index, scene in enumerate(scenes):
            if scene.group == held_out:
                continue
            self.sources[index] = rasterio.open(ROOT / scene.record['source_tif'])
            group = self.eligible.setdefault(scene.group, {})
            for cls in CLASS_IDS:
                if len(scene.pixels[cls]):
                    group.setdefault(cls, []).append(index)
        assert all(scenes[i].group != held_out for i in self.sources)

    def close(self):
        for source in self.sources.values():
            source.close()

    def sample(self):
        for _ in range(20):
            group = self.rng.choice(list(self.eligible))
            cls = int(self.rng.choice(list(self.eligible[group])))
            index = int(self.rng.choice(self.eligible[group][cls]))
            scene = self.scenes[index]
            flat = int(self.rng.choice(scene.pixels[cls]))
            row, col = divmod(flat, scene.mask.shape[1])
            y = int(np.clip(row - PATCH // 2, 0, scene.mask.shape[0] - PATCH))
            x = int(np.clip(col - PATCH // 2, 0, scene.mask.shape[1] - PATCH))
            data = self.sources[index].read(window=Window(x, y, PATCH, PATCH))
            image, valid = normalized_input(data, self.mean, self.std)
            target = scene.mask[y:y + PATCH, x:x + PATCH].copy()
            target[~valid] = 255
            if np.count_nonzero(target != 255) < 256:
                continue
            target[target == 3] = 2
            turns = int(self.rng.integers(0, 4))
            image, target = np.rot90(image, turns, axes=(1, 2)), np.rot90(target, turns)
            if self.rng.integers(0, 2):
                image, target = image[:, :, ::-1], target[:, ::-1]
            if self.rng.integers(0, 2):
                image, target = image[:, ::-1, :], target[::-1, :]
            return np.ascontiguousarray(image), np.ascontiguousarray(target.astype('int64'))
        raise ValueError('Could not draw a patch with at least 256 labelled pixels')

    def batch(self, count):
        pairs = [self.sample() for _ in range(count)]
        return np.stack([x for x, _ in pairs]), np.stack([y for _, y in pairs])


def rf_eval_indices(scene):
    """Mirror train_multiclass.sample_scene's RNG calls exactly."""
    seed = int.from_bytes(hashlib.sha256(scene.record['png'].encode()).digest()[:8], 'big') ^ SEED
    rng = np.random.default_rng(seed)
    for cls in CLASS_IDS:
        ids = scene.pixels[cls]
        if len(ids):
            rng.choice(ids, min(len(ids), 3000), replace=False)
    labelled = np.flatnonzero(scene.mask.ravel() != 255)
    return rng.choice(labelled, min(len(labelled), EVAL_PER_SCENE), replace=False)
