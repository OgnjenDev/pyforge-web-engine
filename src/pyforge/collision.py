"""Rectangle collision helpers.

Everything here works on any object with ``x``, ``y``, ``width`` and
``height`` attributes, so it is not tied to :class:`pyforge.Sprite`.

Two rectangles collide when their interiors overlap. Rectangles that only
touch along an edge do *not* collide. Rectangles with a zero width or height
never collide. Negative sizes are treated as rectangles that extend to the
left / upwards.
"""
from __future__ import annotations

from typing import Any, Iterable, List


def rects_overlap(
    ax: float, ay: float, aw: float, ah: float,
    bx: float, by: float, bw: float, bh: float,
) -> bool:
    """Return True if rectangle A and rectangle B overlap."""
    if aw < 0:
        ax, aw = ax + aw, -aw
    if ah < 0:
        ay, ah = ay + ah, -ah
    if bw < 0:
        bx, bw = bx + bw, -bw
    if bh < 0:
        by, bh = by + bh, -bh
    if aw == 0 or ah == 0 or bw == 0 or bh == 0:
        return False
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def collides(a: Any, b: Any) -> bool:
    """Return True if two rectangle-like objects overlap."""
    return rects_overlap(a.x, a.y, a.width, a.height, b.x, b.y, b.width, b.height)


def collisions(subject: Any, others: Iterable[Any]) -> List[Any]:
    """Return the objects in ``others`` that overlap ``subject``.

    ``subject`` itself is never included, even if it is in ``others``.
    """
    return [o for o in list(others) if o is not subject and collides(subject, o)]


def contains_point(rect: Any, px: float, py: float) -> bool:
    """Return True if the point (px, py) lies inside the rectangle.

    The left and top edges are inside, the right and bottom edges are not.
    """
    x, y, w, h = rect.x, rect.y, rect.width, rect.height
    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h
    return x <= px < x + w and y <= py < y + h
