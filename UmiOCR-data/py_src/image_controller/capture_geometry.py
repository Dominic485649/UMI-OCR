import math


def logical_to_physical_rect(x, y, width, height, scale_x, scale_y, pixel_width, pixel_height):
    values = (x, y, width, height, scale_x, scale_y)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Screenshot coordinates must be finite.")
    if scale_x <= 0 or scale_y <= 0 or pixel_width <= 0 or pixel_height <= 0:
        raise ValueError("Screenshot scale and pixel dimensions must be positive.")

    x0, x1 = sorted((x, x + width))
    y0, y1 = sorted((y, y + height))
    left = max(0, min(pixel_width, math.floor(x0 * scale_x)))
    top = max(0, min(pixel_height, math.floor(y0 * scale_y)))
    right = max(left, min(pixel_width, math.ceil(x1 * scale_x)))
    bottom = max(top, min(pixel_height, math.ceil(y1 * scale_y)))
    return left, top, right - left, bottom - top
