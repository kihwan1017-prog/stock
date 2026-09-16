"""Walk-forward splits + sample confidence bands."""

from __future__ import annotations

from typing import Sequence, TypeVar

T = TypeVar("T")


def chronological_splits(
    rows: Sequence[T],
    *,
    train_frac: float = 0.60,
    val_frac: float = 0.20,
) -> tuple[list[T], list[T], list[T]]:
    """시간 정렬된 행을 train/val/test로 분할. 셔플 금지."""

    n = len(rows)
    if n == 0:
        return [], [], []
    i_train = int(n * train_frac)
    i_val = int(n * (train_frac + val_frac))
    if i_train < 1 and n >= 1:
        i_train = max(1, n // 3)
    if i_val <= i_train:
        i_val = min(n, i_train + max(1, (n - i_train) // 2))
    train = list(rows[:i_train])
    val = list(rows[i_train:i_val])
    test = list(rows[i_val:])
    return train, val, test


def confidence_from_n(n: int) -> str:
    if n < 30:
        return "VERY_LOW"
    if n < 100:
        return "LOW"
    if n < 300:
        return "MEDIUM"
    return "MEDIUM_HIGH"
