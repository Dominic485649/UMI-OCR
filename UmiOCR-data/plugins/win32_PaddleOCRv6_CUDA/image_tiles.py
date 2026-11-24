"""大图分块与原图坐标合并，不导入推理框架。"""
import math

MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_PIXELS = 64 * 1024 * 1024
MAX_IMAGE_SIDE = 50000
MAX_TILES = 64


def check_size(width, height):
    if (width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS
            or max(width, height) > MAX_IMAGE_SIDE):
        raise ValueError("IMAGE_BUDGET_EXCEEDED")


def _positions(length, side, overlap):
    if length <= side:
        return [0]
    values = list(range(0, length - side + 1, side - overlap))
    if values[-1] != length - side:
        values.append(length - side)
    return values


def tiles(width, height, side):
    check_size(width, height)
    side = max(640, min(int(side), 8000))
    overlap = min(256, max(64, side // 12))
    values = [(x, y, min(width, x + side), min(height, y + side))
              for y in _positions(height, side, overlap)
              for x in _positions(width, side, overlap)]
    if len(values) > MAX_TILES:
        raise ValueError("IMAGE_TILE_BUDGET_EXCEEDED")
    return values


def _bounds(box):
    xs, ys = [point[0] for point in box], [point[1] for point in box]
    return min(xs), min(ys), max(xs), max(ys)


def _cells(box):
    x1, y1, x2, y2 = box
    return [(x, y) for x in range(math.floor(x1 / 256), math.floor(x2 / 256) + 1)
            for y in range(math.floor(y1 / 256), math.floor(y2 / 256) + 1)]


def merge(items):
    """相同文字仅在明显重叠时合并，用空间索引避免全表平方扫描。"""
    kept, buckets = [], {}
    for item in sorted(items, key=lambda value: value.get("score", 0), reverse=True):
        a = _bounds(item["box"])
        normalized = item["text"].strip()
        cells = _cells(a)
        candidates = set()
        for cell in cells:
            candidates.update(buckets.get((normalized, *cell), ()))
        duplicate = False
        for index in candidates:
            b = _bounds(kept[index]["box"])
            overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
            area_a = max(1, (a[2] - a[0]) * (a[3] - a[1]))
            area_b = max(1, (b[2] - b[0]) * (b[3] - b[1]))
            if overlap / min(area_a, area_b) >= 0.6:
                duplicate = True
                break
        if not duplicate:
            index = len(kept)
            kept.append(item)
            for cell in cells:
                buckets.setdefault((normalized, *cell), []).append(index)
    return sorted(kept, key=lambda value: (_bounds(value["box"])[1], _bounds(value["box"])[0]))
