import math

def distance_parsecs(pos1, pos2, pixels_per_parsec=10):
    dx = pos1.x - pos2.x
    dy = pos1.y - pos2.y
    distance_pixels = math.hypot(dx, dy)
    return round(distance_pixels / pixels_per_parsec, 1)
