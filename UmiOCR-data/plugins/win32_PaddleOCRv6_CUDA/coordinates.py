import math

import numpy as np


def _sample_grid(grid, x, y):
    grid = np.asarray(grid, dtype=np.float32)
    if grid.ndim == 4:
        grid = grid[0]
    if grid.ndim != 3 or grid.shape[2] != 2:
        raise ValueError(f"Invalid UVDoc grid shape: {grid.shape}")
    height, width = grid.shape[:2]
    x = min(max(float(x), 0.0), width - 1.0)
    y = min(max(float(y), 0.0), height - 1.0)
    x0, y0 = int(math.floor(x)), int(math.floor(y))
    x1, y1 = min(x0 + 1, width - 1), min(y0 + 1, height - 1)
    dx, dy = x - x0, y - y0
    top = grid[y0, x0] * (1.0 - dx) + grid[y0, x1] * dx
    bottom = grid[y1, x0] * (1.0 - dx) + grid[y1, x1] * dx
    return top * (1.0 - dy) + bottom * dy


def _inverse_rotation(point, angle, original_shape):
    if angle in (-1, 0):
        return point
    height, width = original_shape[:2]
    center = np.array([width / 2.0, height / 2.0], dtype=np.float64)
    radians = math.radians(angle)
    cosine, sine = abs(math.cos(radians)), abs(math.sin(radians))
    rotated_size = np.array(
        [int(height * sine + width * cosine), int(height * cosine + width * sine)],
        dtype=np.float64,
    )
    translated = np.asarray(point, dtype=np.float64) - rotated_size / 2.0
    inverse = np.array(
        [[math.cos(radians), -math.sin(radians)], [math.sin(radians), math.cos(radians)]]
    )
    return inverse @ translated + center


def restore_polygon(polygon, preprocessor_result):
    angle = int(preprocessor_result.get("angle", -1))
    original = np.asarray(preprocessor_result["input_img"])
    rotated = np.asarray(preprocessor_result.get("rot_img", original))
    grid = preprocessor_result.get("grid")
    restored = []
    for x, y in polygon:
        if grid is not None:
            gx, gy = _sample_grid(grid, x, y)
            point = np.array(
                [
                    (float(gx) + 1.0) * (rotated.shape[1] - 1) / 2.0,
                    (float(gy) + 1.0) * (rotated.shape[0] - 1) / 2.0,
                ]
            )
        else:
            point = np.array([x, y], dtype=np.float64)
        ox, oy = _inverse_rotation(point, angle, original.shape)
        restored.append(
            [
                int(round(min(max(ox, 0.0), original.shape[1] - 1.0))),
                int(round(min(max(oy, 0.0), original.shape[0] - 1.0))),
            ]
        )
    return restored
