import random


class Rng:
    def __init__(self, seed: int | None = None) -> None:
        self._random = random.Random(seed)

    def roll(self, sides: int) -> int:
        if sides < 1:
            raise ValueError("die must have at least 1 side")
        return self._random.randint(1, sides)

    def roll_d20(self) -> int:
        return self.roll(20)


class FixedRng:
    """Deterministic RNG that replays a fixed sequence of rolls (test seam)."""

    def __init__(self, rolls: list[int]) -> None:
        self._rolls = list(rolls)
        self._index = 0

    def roll(self, sides: int) -> int:
        if self._index >= len(self._rolls):
            raise IndexError("FixedRng ran out of rolls")
        value = self._rolls[self._index]
        self._index += 1
        if not 1 <= value <= sides:
            raise ValueError(f"forced roll {value} out of range for d{sides}")
        return value

    def roll_d20(self) -> int:
        return self.roll(20)
