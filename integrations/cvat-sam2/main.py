"""CVAT interactor for SAM 2.1 Small; returns native-grid CVAT masks."""
import base64
import io
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError


def mask_to_rle(mask):
    """Row-major, background-first CVAT RLE with inclusive bounding box."""
    yy, xx = np.nonzero(mask)
    if not len(xx):
        return []
    left, top, right, bottom = map(int, (xx.min(), yy.min(), xx.max(), yy.max()))
    pixels = mask[top:bottom + 1, left:right + 1].reshape(-1).astype(bool)
    changes = np.flatnonzero(pixels[1:] != pixels[:-1]) + 1
    runs = np.diff(np.r_[0, changes, pixels.size]).tolist()
    if pixels[0]:
        runs.insert(0, 0)
    return runs + [left, top, right, bottom]


def prompt_points(value, width, height):
    points = np.asarray(value, dtype=float)
    if points.size == 0:
        return np.empty((0, 2))
    if points.ndim != 2 or points.shape[1] != 2 or len(points) > 1000:
        raise ValueError('Expected at most 1000 x/y points')
    if not np.isfinite(points).all() or (points < 0).any() or (points > [width - 1, height - 1]).any():
        raise ValueError('Prompt coordinates are outside the image')
    return points


class ModelHandler:
    def __init__(self):
        import torch
        from ultralytics import SAM
        torch.set_num_threads(4)
        checkpoint = Path(os.environ.get('SAM2_CHECKPOINT', '/opt/nuclio/sam2.1_s.pt'))
        if not checkpoint.is_file():
            raise FileNotFoundError(checkpoint)
        self.model = SAM(str(checkpoint))

    def handle(self, image, data):
        width, height = image.size
        pos = prompt_points(data.get('pos_points', []), width, height)
        neg = prompt_points(data.get('neg_points', []), width, height)
        box = prompt_points(data.get('obj_bbox') or [], width, height)
        if len(box) != 2 or (box[1] <= box[0]).any():
            raise ValueError('Draw a non-empty bounding box first')
        points = np.concatenate((pos, neg))
        # Include prompts outside the box and 64 pixels of surrounding context.
        extent = np.concatenate((box, points))
        left, top = np.maximum(0, np.floor(extent.min(axis=0)) - 64).astype(int)
        right, bottom = np.minimum([width, height], np.ceil(extent.max(axis=0)) + 65).astype(int)
        crop = image.crop((left, top, right, bottom))
        prompts = {'bboxes': [(box - [left, top]).reshape(-1).tolist()]}
        if len(points):
            prompts.update(points=[(points - [left, top]).tolist()], labels=[[1] * len(pos) + [0] * len(neg)])
        # One worker serializes requests. Reset prevents stale image features.
        if self.model.predictor is not None:
            self.model.predictor.reset_image()
        result = self.model.predict(crop, device='cpu', verbose=False, save=False, **prompts)[0]
        if result.masks is None or len(result.masks.data) == 0:
            return []
        selected = result.masks.data[0].cpu().numpy() > 0.5
        if selected.shape != (bottom - top, right - left):
            raise RuntimeError('Model mask dimensions differ from crop')
        rle = mask_to_rle(selected)
        if rle:
            rle[-4:] = [rle[-4] + int(left), rle[-3] + int(top), rle[-2] + int(left), rle[-1] + int(top)]
        return rle


def init_context(context):
    context.user_data.model = ModelHandler()


def handler(context, event):
    try:
        data = event.body
        if isinstance(data, (str, bytes)):
            data = json.loads(data)
        if not isinstance(data, dict) or not isinstance(data.get('image'), str):
            raise ValueError('Expected image and prompts')
        if len(data['image']) > 32 * 1024 * 1024:
            raise ValueError('Encoded image exceeds 32 MiB')
        with Image.open(io.BytesIO(base64.b64decode(data['image'], validate=True))) as source:
            if source.width * source.height > 20_000_000:
                raise ValueError('Image exceeds 20 million pixels; use a smaller ROI')
            image = source.convert('RGB')
        rle = context.user_data.model.handle(image, data)
        shapes = [] if not rle else [dict(type='mask', points=rle, group=0, source='semi-auto', attributes=[], occluded=False, rotation=0)]
        body, status = {'shapes': shapes}, 200
    except (ValueError, TypeError, UnidentifiedImageError) as error:
        body, status = {'error': str(error)}, 400
    return context.Response(body=json.dumps(body), headers={}, content_type='application/json', status_code=status)
