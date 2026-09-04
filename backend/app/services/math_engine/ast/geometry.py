from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .base import GeometryObject


@dataclass(slots=True)
class Point(GeometryObject):
    name: str
    x: float
    y: float
    z: float = 0.0

    def to_latex(self) -> str:
        return f"{self.name}\\left({self.x}, {self.y}\\right)"

    def to_plain(self) -> str:
        return f"{self.name}({self.x}, {self.y})"

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "point", "name": self.name, "x": self.x, "y": self.y, "z": self.z}

    def distance_to(self, other: Point) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


@dataclass(slots=True)
class Vector(GeometryObject):
    x: float
    y: float
    z: float = 0.0

    def magnitude(self) -> float:
        return math.sqrt(self.x**2 + self.y**2 + self.z**2)

    def dot(self, other: Vector) -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z

    def to_latex(self) -> str:
        return f"\\begin{{pmatrix}} {self.x} \\\\ {self.y} \\end{{pmatrix}}"

    def to_plain(self) -> str:
        return f"({self.x}, {self.y})"

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "vector", "x": self.x, "y": self.y, "z": self.z, "magnitude": self.magnitude()}


@dataclass(slots=True)
class Segment(GeometryObject):
    start: Point
    end: Point
    label: str = ""

    def length(self) -> float:
        return self.start.distance_to(self.end)

    def to_latex(self) -> str:
        lbl = f" = {self.label}" if self.label else ""
        return f"|{self.start.name}{self.end.name}|{lbl}"

    def to_plain(self) -> str:
        return f"Segment {self.start.name}{self.end.name}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "segment",
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
            "length": self.length(),
            "label": self.label,
        }


@dataclass(slots=True)
class Ray(GeometryObject):
    start: Point
    direction: Vector

    def to_latex(self) -> str:
        return f"\\vec{{{self.start.name}}}"

    def to_plain(self) -> str:
        return f"Ray from {self.start.name}"

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "ray", "start": self.start.to_dict(), "direction": self.direction.to_dict()}


@dataclass(slots=True)
class Polygon(GeometryObject):
    vertices: List[Point]
    name: str = ""

    def perimeter(self) -> float:
        n = len(self.vertices)
        if n < 3:
            return 0.0
        return sum(self.vertices[i].distance_to(self.vertices[(i + 1) % n]) for i in range(n))

    def to_latex(self) -> str:
        names = "".join(v.name for v in self.vertices)
        return f"\\text{{Polygon}}\\ {names}"

    def to_plain(self) -> str:
        return f"Polygon with {len(self.vertices)} vertices"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "polygon",
            "name": self.name,
            "vertices": [v.to_dict() for v in self.vertices],
            "perimeter": self.perimeter(),
        }


@dataclass(slots=True)
class Angle(GeometryObject):
    vertex: Point
    arm1_point: Point
    arm2_point: Point
    degrees: Optional[float] = None
    label: str = ""

    def to_latex(self) -> str:
        name = f"\\angle {self.arm1_point.name}{self.vertex.name}{self.arm2_point.name}"
        if self.degrees is not None:
            return f"{name} = {self.degrees}^\\circ"
        return name

    def to_plain(self) -> str:
        d_str = f" = {self.degrees}°" if self.degrees is not None else ""
        return f"Angle {self.arm1_point.name}{self.vertex.name}{self.arm2_point.name}{d_str}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "angle",
            "vertex": self.vertex.name,
            "arms": [self.arm1_point.name, self.arm2_point.name],
            "degrees": self.degrees,
            "label": self.label,
        }


@dataclass(slots=True)
class Triangle(GeometryObject):
    a: Point
    b: Point
    c: Point
    base: Optional[float] = None
    height: Optional[float] = None
    side_a: Optional[float] = None  # opposite point A (i.e. length BC)
    side_b: Optional[float] = None  # opposite point B (i.e. length AC)
    side_c: Optional[float] = None  # opposite point C (i.e. length AB)

    def __post_init__(self):
        if self.side_c is None:
            self.side_c = self.a.distance_to(self.b)
        if self.side_a is None:
            self.side_a = self.b.distance_to(self.c)
        if self.side_b is None:
            self.side_b = self.a.distance_to(self.c)
        if self.base is None:
            self.base = self.side_c

    def perimeter(self) -> float:
        return (self.side_a or 0) + (self.side_b or 0) + (self.side_c or 0)

    def area(self) -> float:
        if self.base is not None and self.height is not None:
            return 0.5 * self.base * self.height
        # Heron's formula
        s = self.perimeter() / 2.0
        a, b, c = self.side_a or 0, self.side_b or 0, self.side_c or 0
        val = s * (s - a) * (s - b) * (s - c)
        return math.sqrt(max(0.0, val))

    def is_right_angled(self) -> bool:
        sides = sorted([self.side_a or 0, self.side_b or 0, self.side_c or 0])
        return math.isclose(sides[0]**2 + sides[1]**2, sides[2]**2, rel_tol=1e-5)

    def to_latex(self) -> str:
        return f"\\triangle {self.a.name}{self.b.name}{self.c.name}"

    def to_plain(self) -> str:
        return f"Triangle {self.a.name}{self.b.name}{self.c.name}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "triangle",
            "vertices": [self.a.to_dict(), self.b.to_dict(), self.c.to_dict()],
            "base": self.base,
            "height": self.height,
            "side_a": self.side_a,
            "side_b": self.side_b,
            "side_c": self.side_c,
            "area": round(self.area(), 4),
            "perimeter": round(self.perimeter(), 4),
            "is_right_angled": self.is_right_angled(),
        }


@dataclass(slots=True)
class Quadrilateral(GeometryObject):
    a: Point
    b: Point
    c: Point
    d: Point
    kind: str = "rectangle"  # rectangle, square, parallelogram, trapezium, rhombus
    length: Optional[float] = None
    width: Optional[float] = None
    parallel_side1: Optional[float] = None
    parallel_side2: Optional[float] = None
    height: Optional[float] = None

    def area(self) -> float:
        if self.kind in ("rectangle", "square"):
            l = self.length or self.a.distance_to(self.b)
            w = self.width or self.b.distance_to(self.c)
            return l * w
        if self.kind == "parallelogram":
            b = self.length or self.a.distance_to(self.b)
            h = self.height or 1.0
            return b * h
        if self.kind == "trapezium":
            a = self.parallel_side1 or 1.0
            b = self.parallel_side2 or 1.0
            h = self.height or 1.0
            return 0.5 * (a + b) * h
        return 0.0

    def to_latex(self) -> str:
        return f"\\text{{{self.kind.capitalize()}}}\\ {self.a.name}{self.b.name}{self.c.name}{self.d.name}"

    def to_plain(self) -> str:
        return f"{self.kind.capitalize()} {self.a.name}{self.b.name}{self.c.name}{self.d.name}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "quadrilateral",
            "kind": self.kind,
            "vertices": [self.a.to_dict(), self.b.to_dict(), self.c.to_dict(), self.d.to_dict()],
            "area": self.area(),
        }


@dataclass(slots=True)
class Circle(GeometryObject):
    center: Point
    radius: float

    def diameter(self) -> float:
        return 2 * self.radius

    def circumference(self) -> float:
        return 2 * math.pi * self.radius

    def area(self) -> float:
        return math.pi * (self.radius ** 2)

    def to_latex(self) -> str:
        return f"\\odot {self.center.name}\\ (r = {self.radius})"

    def to_plain(self) -> str:
        return f"Circle centered at {self.center.name} with radius {self.radius}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "circle",
            "center": self.center.to_dict(),
            "radius": self.radius,
            "diameter": self.diameter(),
            "circumference": round(self.circumference(), 4),
            "area": round(self.area(), 4),
        }


@dataclass(slots=True)
class Sector(GeometryObject):
    circle: Circle
    angle_degrees: float

    def arc_length(self) -> float:
        return (self.angle_degrees / 360.0) * self.circle.circumference()

    def area(self) -> float:
        return (self.angle_degrees / 360.0) * self.circle.area()

    def perimeter(self) -> float:
        return self.arc_length() + 2 * self.circle.radius

    def to_latex(self) -> str:
        return f"\\text{{Sector}}\\ (\\theta = {self.angle_degrees}^\\circ, r = {self.circle.radius})"

    def to_plain(self) -> str:
        return f"Sector of angle {self.angle_degrees}° in circle radius {self.circle.radius}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "sector",
            "circle": self.circle.to_dict(),
            "angle_degrees": self.angle_degrees,
            "arc_length": round(self.arc_length(), 4),
            "area": round(self.area(), 4),
            "perimeter": round(self.perimeter(), 4),
        }
