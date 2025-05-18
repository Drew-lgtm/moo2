import random
from core.star import Star

class Galaxy:
    def __init__(self, num_stars, width, height):
        self.stars = [
            Star(
                x=random.randint(50, width - 50),
                y=random.randint(50, height - 50),
                name=f"Star {i}",
                num_planets=random.randint(1, 5)
            )
            for i in range(num_stars)
        ]
