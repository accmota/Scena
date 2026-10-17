from typing import Any, Optional, Union, Tuple, overload, List, Dict, Any, Iterator, Set, TypeVar, Generic, Callable
from .state import (
    Attribute, Container, ContainerSet, FieldType, ScalarSlot, ScalarAnchor,
    batch_update_self, ephemeral_creation, _init_scalar, as_payload, bump_pose_rev,
    _point_index_refusal,
)
from .closed import _DEPTH, _SEALED, make_closed_setattr, seal_after_init
import inspect
import math
import random

from .purity_check import _READING as _SOLVER_READING, refuse_if_solver_reading


def clip(value: float, min_val: float, max_val: float) -> float:
    """Clip a value between min and max values."""
    return min(max(value, min_val), max_val)


def _as_coord(v) -> float:
    """Bare float from a number, Attribute, or scalar anchor."""
    if isinstance(v, Attribute):
        return float(v.value)
    if isinstance(v, ScalarAnchor):
        return float(v.value)
    return float(v)


def _vec_arg(value, what: str) -> "Vec2":
    """Operand of a Vec2 method: a Vec2, or an ``(x, y)`` pair like ``+`` /
    ``-`` accept. Anything else raises a Scena ``TypeError`` (A9)."""
    if isinstance(value, Vec2):
        return value
    value = as_payload(value)
    if isinstance(value, Vec2):
        return value
    from .validate import pair
    x, y = pair(value, what)
    return Vec2.temp(x=x, y=y)


def _scalar_arg(value, what: str) -> float:
    """A number argument off the fast path (VB13): a cell counts as its
    number, a bracket handle gets the words ``float(st["x"])`` gives, anything
    else the Numbers rule's."""
    from .state import FieldRef, field_ref_value_message
    if isinstance(value, FieldRef):
        raise TypeError(field_ref_value_message(value))
    from .validate import number
    return number(as_payload(value), what)


def _vec_operand_message(verb: str, other) -> str:
    """``v + 5`` / ``v - "a"``: say what the other side may be, and the fix.

    A Point is refused on purpose: it is a place, a Vec2 a displacement."""
    kind = type(other).__name__
    if kind == "Point":
        return (f"Cannot {verb} Vec2 and Point: a Point is a place, a Vec2 a "
                "displacement. The vector between two points is p - q; to move "
                "a point by a vector, write p + v.")
    fix = " To move by the same amount on both axes, write v + (5, 5)." if isinstance(
        other, (int, float)) and not isinstance(other, bool) else ""
    return (
        f"Cannot {verb} Vec2 and {kind} {other!r:.40}. The other side must be a "
        f"Vec2 or an (x, y) pair.{fix}"
    )


def _vec_scale_message(op: str, other) -> str:
    """``v * "a"``: a Vec2 scales by a number only."""
    kind = type(other).__name__
    hint = " For a dot product write v.dot(w)." if isinstance(other, Vec2) else ""
    return f"Vec2 {op} {kind}: a Vec2 scales by a number, as in v {op} 2.{hint}"


def _vec_overflow_message(other) -> str:
    """``v += (10**400, 0)``: an int no float holds (GX15's words, not Python's
    OverflowError)."""
    r = repr(tuple(other)) if isinstance(other, (tuple, list)) else repr(other)
    return f"a vector takes two finite numbers, got {r if len(r) <= 40 else r[:39] + '…'}"

class Vec2(Container):
    """
    2D vector class. ``x``/``y`` are bare Defining scalars; ``length``
    and ``angle`` are bare Derivate scalars (ScalarSlot).
    Supports all standard vector operations and various utility methods.
    
    Constructor signatures:
    (see __new__ signatures for proper usage, not all parameters are required at the same time)
      - Vec2() - Create a zero vector (0, 0)
      - Vec2(100, 200) - Create vector with x=100, y=200 (positional arguments)
      - Vec2(x=100, y=200) - Create vector with specific x and y coordinates
      - Vec2(tuple=(100, 200)) - Create vector from a tuple of coordinates
      - Vec2(lambda: v1 + v2) - Create vector from a lambda function

    Common optional parameters (passed via **kwargs):
      - attr_name: Optional[str] - Attribute name for the vector
      - owner: Optional[Container] - Owner container for the vector
    """
    
    x = ScalarSlot()
    y = ScalarSlot()
    length = ScalarSlot(FieldType.Derivate)
    _scena_point_value = True       # iterates as (x, y); see Point
    angle = ScalarSlot(FieldType.Derivate)

    # Closed surface (scena.closed): ``v.lenght = 5`` raises. The axes pass
    # first. Construction makes no ``__setattr__`` call (Container fields go
    # through ``__dict__``, ``_container_dict_init``; the seal is a ``__dict__``
    # mark at the end of ``__init__``), so arithmetic costs what an open Vec2
    # did; only a direct write such as ``v.x = 5`` pays the Python call (~100 ns).
    __setattr__ = make_closed_setattr(("x", "y", "length", "angle"))

    def __init_subclass__(cls, **kwargs):
        # An author subclass with its own __init__ seals when that returns.
        super().__init_subclass__(**kwargs)
        seal_after_init(cls)

    # The list of valid signatures, each with (name, exact_keys)
    _CONSTRUCTOR_SIGNATURES = [
        ("default",        set()),
        ("xy",            {"x", "y"}),
        ("tuple",         {"tuple"}),
        ("lambda",        {"lambda"}),
    ]

    @classmethod
    def temp(cls, x: float = 0.0, y: float = 0.0) -> 'Vec2':
        """Create an unregistered Vec2 for use as an arithmetic result.

        Always copies bare numeric values — never links to Attribute sources.
        """
        if isinstance(x, Attribute):
            x = x.value
        if isinstance(y, Attribute):
            y = y.value
        try:
            x = float(x)
            y = float(y)
        except OverflowError:
            # ``v + (10**400, 0)``, ``v * 10**400``: GX15's words, not Python's (VB5).
            raise ValueError(_vec_overflow_message((x, y))) from None
        if cls is Vec2 and _isfinite(x) and _isfinite(y):
            # Fast path (every arithmetic result): the state the general
            # constructor below leaves, written in one ``__dict__`` update.
            # Reactive Design, "Vec2 (scenamath.py)"; guard:
            # test_vec2_temp_fast_path (same dict as the general path).
            system = _state._global_scena_system
            if system is not None:
                v = _object_new(Vec2)
                d = v.__dict__
                d.update(_TEMP_STATE)
                d['_scena_system'] = system
                d['_parts'] = ContainerSet()
                d['x'] = x
                d['y'] = y
                return v
        with ephemeral_creation():
            return cls(x=x, y=y)

    @overload
    def __new__(cls) -> 'Vec2': ...
    
    @overload
    def __new__(cls, x: Union[float, Attribute], y: Union[float, Attribute], **kwargs) -> 'Vec2': ...
    
    @overload
    def __new__(cls, *, x: Union[float, Attribute], y: Union[float, Attribute], **kwargs) -> 'Vec2': ...
    
    @overload
    def __new__(cls, *, tuple: Union[Tuple[float, float], Tuple[Attribute, Attribute]], **kwargs) -> 'Vec2': ...
    
    @overload
    def __new__(cls, *, x: Union[float, Attribute], **kwargs) -> 'Vec2': ...
    
    def __new__(cls, *args, **kwargs):
        processed_params = {}
        
        # Handle positional arguments
        if len(args) == 2:
            # Check for conflicting keyword arguments
            conflicting_keys = {'x', 'y', 'tuple'} & set(kwargs.keys())
            if conflicting_keys:
                raise TypeError(f"Cannot use positional arguments with keyword arguments: {conflicting_keys}")
            
            # Convert positional args to keyword args
            processed_params['x'] = args[0]
            processed_params['y'] = args[1]
        elif len(args) == 1:
            # Check for conflicting keyword arguments
            conflicting_keys = {'x', 'y', 'tuple'} & set(kwargs.keys())
            if conflicting_keys:
                raise TypeError(f"Cannot use positional arguments with keyword arguments: {conflicting_keys}")
            
            if isinstance(args[0], tuple):
                # Convert tuple to keyword args
                if len(args[0]) != 2:
                    raise ValueError(f"Tuple must have exactly 2 elements, got {len(args[0])}")
                processed_params['tuple'] = args[0]
            elif callable(args[0]) and args[0].__name__ == '<lambda>':
                # Lambda function - treat as lambda parameter
                processed_params['lambda'] = args[0]
            else:
                raise TypeError(
                    f"Vec2() takes two numbers, a 2-tuple, or a lambda; got "
                    f"{type(args[0]).__name__} {args[0]!r}. Write Vec2(3, 4), "
                    f"Vec2((3, 4)) or Vec2(lambda: (mouse.x, mouse.y))."
                )
        elif len(args) > 0:
            raise TypeError(
                f"Vec2() takes two numbers, a 2-tuple, or a lambda; got {len(args)} "
                f"positional values. Write Vec2(3, 4)."
            )
        
        # Create the instance
        instance = super().__new__(cls)
        
        # Hand the processed parameters to __init__ (through __dict__: no
        # __setattr__ call on the construction path)
        instance.__dict__['_processed_params'] = processed_params
        
        return instance

    def _set_init_coordinates(self, x: Union[float, Attribute], y: Union[float, Attribute]) -> None:
        """Bare values copy; callables install a live link."""
        _init_scalar(self, 'x', x)
        _init_scalar(self, 'y', y)
    
    def __init__(self, *args, **kwargs):
        # Merge processed parameters from __new__ with original kwargs
        d = self.__dict__
        processed_params = d.pop('_processed_params', None)
        if processed_params is not None:
            # Merge: processed_params take precedence over original kwargs
            merged_kwargs = kwargs.copy()
            merged_kwargs.update(processed_params)
            kwargs = merged_kwargs
        
        # Extract common Container parameters and determine signature
        base_params, signature = self._extract_common_params_and_signature(
            kwargs=kwargs, 
            valid_signatures=self._CONSTRUCTOR_SIGNATURES
        )

        # Initialize the Container
        Container.__init__(self, **base_params)

        # Dispatch to the right initialization path based on signature:
        match signature:
            case "default":
                # Example: Vec2()
                self._set_init_coordinates(0.0, 0.0)
                
            case "xy":
                # Example: Vec2(x=100, y=200)
                x = kwargs['x']
                y = kwargs['y']
                self._set_init_coordinates(x, y)
                
            case "tuple":
                # Example: Vec2(tuple=(100, 200))
                coord_tuple = kwargs['tuple']
                from .validate import pair
                if not any(callable(c) or hasattr(c, "_link") for c in (
                        coord_tuple if isinstance(coord_tuple, tuple) else ())):
                    pair(coord_tuple, "Vec2 tuple")   # plain values: must be (x, y)
                self._set_init_coordinates(coord_tuple[0], coord_tuple[1])
                
            case "lambda":
                # Example: Vec2(lambda=lambda: v1 + v2)
                lambda_fn = kwargs['lambda']
                self._assign_formula(lambda_fn)

            case _:
                raise ValueError(f"Unknown signature: {signature}")

        # Seal unless a subclass __init__ (seal_after_init) is still running:
        # that one seals when it returns.
        if _DEPTH not in d:
            d[_SEALED] = True

    __signature__ = inspect.Signature([
        inspect.Parameter("x", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None),
        inspect.Parameter("y", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None),
        inspect.Parameter("tuple", inspect.Parameter.KEYWORD_ONLY, default=None),
    ])

    @classmethod
    def _extract_common_params_and_signature(cls, kwargs: Dict[str, Any], 
                                            valid_signatures: List[Tuple[str, Set[str]]]) -> Tuple[Dict[str, Any], str]:
        """
        Extract common Container parameters and determine the signature for vector construction.
        
        Args:
            kwargs: All keyword arguments passed to the constructor
            valid_signatures: List of (signature_name, required_keys) tuples
        Returns:
            Tuple of (base_params, signature_name) where base_params contains owner, attr_name
        """
        # Extract common Container parameters
        attr_name = kwargs.get('attr_name')
        owner = kwargs.get('owner')
        if attr_name is None:
            attr_name = "vec2"

        base_params = {'attr_name': attr_name, 'owner': owner}
        
        # Calculate vector_keys from valid_signatures
        vector_keys = set()
        for _, keys in valid_signatures:
            vector_keys.update(keys)

        # Unknown keywords fail loud (``Vec2(1, 2, zz=1)`` used to drop zz; A4).
        leftover = {k: v for k, v in kwargs.items()
                    if k not in vector_keys and k not in ('attr_name', 'owner')}
        if leftover:
            from .validate import reject_unexpected_kwargs
            reject_unexpected_kwargs(cls.__name__, leftover,
                                     valid=vector_keys)
        
        # Determine which signature matches the vector-defining keys in kwargs
        # Which vector-defining keys are actually present in kwargs?
        present_keys = set(kwargs.keys()) & vector_keys

        # Collect any signatures whose required keys exactly match 'present_keys'
        matched_signatures = [
            sig_name
            for sig_name, required_keys in valid_signatures
            if required_keys == present_keys
        ]

        if len(matched_signatures) == 0:
            raise ValueError(f"No matching signature for vector-defining keys: {present_keys}")
        if len(matched_signatures) > 1:
            raise ValueError(f"Multiple matching signatures for keys: {present_keys}. Matches: {matched_signatures}")

        signature = matched_signatures[0]
        
        return base_params, signature

    @batch_update_self()
    def _update_impl(self) -> None:
        """Update internal state variables."""
        # Update length and angle
        # ``_write_field``, not ``self.length =``: an engine store, so the
        # author door's destroyed check (``ScalarSlot.__set__``) does not
        # refuse a read of a dead actor's ``vel.length``.
        length_squared = self.x * self.x + self.y * self.y
        self._write_field('length', math.sqrt(length_squared))
        self._write_field('angle', math.degrees(math.atan2(self.y, self.x)))

    def _derived_field_message(
        self, name: str, operation: str, value: Any = None, part: Optional[str] = None,
    ) -> str:
        """``v.length = 5`` / ``v["angle"] @= …``: name the in-place spelling."""
        shown = (
            f"{value:g}" if isinstance(value, float)
            or (type(value) is int and -1e308 < value < 1e308)     # 10**400 cannot format
            else None
        )
        if operation == "link":
            return (
                f"Vec2.{name} is computed from x and y, so it cannot be linked. "
                f"Link the whole vector instead: "
                f"v @= lambda: vec_from_angle(angle, length)."
            )
        if name == "length":
            fix = (f"To give the vector a new length and keep its direction, write "
                   f"v << vec_from_angle(v.angle, {shown or 'new_length'}).")
        elif name == "angle":
            fix = (f"To turn the vector and keep its length, write "
                   f"v << vec_from_angle({shown or 'degrees'}, v.length).")
        else:
            fix = "Write x and y, or v << vec_from_angle(angle, length)."
        return f"Vec2.{name} is computed from x and y, so it cannot be set. {fix}"

    def _materialize_derivate_part(self, name: str) -> None:
        """Fill lazy length/angle from current x/y on first access."""
        d = self.__dict__
        x = float(d.get('x', 0.0))
        y = float(d.get('y', 0.0))
        if (type(self) is Vec2 and d.get('_node_id') is None and d.get('_owner') is None
                and not d.get('_field_anchors')):
            # A free vector no graph node observes (every arithmetic result):
            # store what the write below would. It would also bump a pose cell
            # and queue it for the collision drain, which no collider reads.
            if name == 'length':
                value = math.sqrt(x * x + y * y)
            elif name == 'angle':
                value = math.degrees(math.atan2(y, x))
            else:
                return
            if _isfinite(value):
                if value != d.get(name, 0.0):
                    d[name] = value
                return
        with self._no_update():      # engine stores (see ``_update_impl``)
            if name == 'length':
                self._write_field('length', math.sqrt(x * x + y * y))
            elif name == 'angle':
                self._write_field('angle', math.degrees(math.atan2(y, x)))

    def _assign_formula(self, formula: Union['Container', Tuple[float, float], Callable[[], Any]]):
        if isinstance(formula, tuple):
            # special case for Vec2 @= (x, y): both axes must be linkable.
            if len(formula) != 2:
                raise ValueError("A tuple of two numbers is expected")

            x, y = formula
            for value in (x, y):
                if not (callable(value) or isinstance(value, Container)):
                    label = self.name or type(self).__name__
                    raise TypeError(
                        f"@= tuple form links both axes — use '{label}.x = value; "
                        f"{label}.y = value' for a plain copy, "
                        f"or '{label}[\"x\"] @= lambda: …' per axis for a partial link"
                    )

            with self._batch_update():
                linked = []
                try:
                    for axis, value in (("x", x), ("y", y)):
                        self._link_field(axis, value)
                        linked.append(axis)
                except Exception:
                    for axis in linked:
                        self._unlink_field(axis)
                    raise
        else:
            super()._assign_formula(formula)

    # Vector operations -------------------------------------------------------------------------------------------------------
    def dot(self, other: 'Vec2') -> float:
        """Compute dot product with another vector."""
        other = _vec_arg(other, "Vec2.dot")
        return self.x * other.x + self.y * other.y

    def cross(self, other: 'Vec2') -> float:
        """Compute cross product magnitude with another vector."""
        other = _vec_arg(other, "Vec2.cross")
        return self.x * other.y - self.y * other.x

    def normalize(self) -> 'Vec2':
        """Return normalized vector (unit length)."""
        n = self.length
        if n > 0:
            return Vec2.temp(x=self.x / n, y=self.y / n)
        return Vec2.temp()

    def rotate(self, angle: float) -> 'Vec2':
        """Return rotated vector by angle (in degrees)."""
        from .validate import number
        rad = math.radians(number(angle, "Vec2.rotate angle"))
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        return Vec2.temp(
            x=self.x * cos_a - self.y * sin_a,
            y=self.x * sin_a + self.y * cos_a
        )

    def perp_right(self) -> 'Vec2':
        """
        Returns the right perpendicular vector (rotated 90° clockwise).
        Efficient implementation without using rotation matrix.
        """
        return Vec2.temp(x=self.y, y=-self.x)

    def perp_left(self) -> 'Vec2':
        """
        Returns the left perpendicular vector (rotated 90° counter-clockwise).
        Efficient implementation without using rotation matrix.
        """
        return Vec2.temp(x=-self.y, y=self.x)

    def lerp(self, other: 'Vec2', t: float) -> 'Vec2':
        """Linear interpolation to another vector. ``t`` is not clamped."""
        other = as_payload(other)
        if not (t.__class__ is float or (t.__class__ is int and -1e308 < t < 1e308)):
            t = _scalar_arg(t, "Vec2.lerp t")
        if not isinstance(other, Vec2):
            raise TypeError(
                f"Vec2.lerp expected Vec2, got {type(other).__name__}"
            )
        return Vec2.temp(
            x=self.x + (other.x - self.x) * t,
            y=self.y + (other.y - self.y) * t
        )

    def distance(self, other) -> float:
        """Euclidean distance to another position (same as free ``distance``)."""
        from .shapes import distance as _distance
        return _distance(self, other)

    def angle_to(self, other: 'Vec2') -> float:
        """
        Get signed angle from this vector to another vector in degrees (-180 to 180).
        Positive is counter-clockwise.
        """
        other = _vec_arg(other, "Vec2.angle_to")
        return math.degrees(math.atan2(self.cross(other), self.dot(other)))

    def abs_angle_to(self, other: 'Vec2') -> float:
        """Compute absolute angle between this vector and another vector in degrees."""
        other = _vec_arg(other, "Vec2.abs_angle_to")
        # ``atan2(|cross|, dot)``, not ``acos(dot / (|a||b|))``: acos is
        # ill-conditioned near 0 and 180, so a vector read 1.2e-6 degrees from
        # itself (VB14). A zero vector gives atan2(0, 0) = 0, as before.
        return math.degrees(math.atan2(abs(self.cross(other)), self.dot(other)))

    def reflect(self, normal: 'Vec2') -> 'Vec2':
        """
        Reflect vector v about a normal vector.
        Useful for collision responses and light calculations.
        """
        normal = _vec_arg(normal, "Vec2.reflect normal").normalize()
        return self - normal * 2 * self.dot(normal)

    def project(self, onto: 'Vec2') -> 'Vec2':
        """
        Project this vector onto another vector.
        Useful for constraint satisfaction and collision resolution.
        """
        onto_normalized = _vec_arg(onto, "Vec2.project onto").normalize()
        return onto_normalized * self.dot(onto_normalized)

    def reject(self, from_vec: 'Vec2') -> 'Vec2':
        """
        Reject this vector from another vector (perpendicular component).
        Complement to project().
        """
        return self - self.project(from_vec)

    def clamp_length(self, min_length: float, max_length: float) -> 'Vec2':
        """
        Clamp this vector's length between min and max values.
        Useful for limiting forces, velocities, etc.
        """
        lo, hi = min_length, max_length
        if not ((lo.__class__ is float or (lo.__class__ is int and -1e308 < lo < 1e308))
                and (hi.__class__ is float or (hi.__class__ is int and -1e308 < hi < 1e308))):
            lo = _scalar_arg(min_length, "Vec2.clamp_length min_length")
            hi = _scalar_arg(max_length, "Vec2.clamp_length max_length")
        n = self.length
        if n == 0:
            return Vec2.temp()
        c = lo if lo > n else n         # max(n, lo), min(…, hi): their ties and NaN,
        c = hi if hi < c else c         # without two builtin calls
        return self * (c / n)

    # Arithmetic operations
    def __add__(self, other):
        """
        Add another Vec2, tuple of floats, or Point to this vector.
        Args:
            other: Vec2, tuple of (float, float), or Point
        Returns:
            Vec2 when adding Vec2 or tuple, Point when adding Point
        """
        if isinstance(other, Vec2):
            return Vec2.temp(x=self.x + other.x, y=self.y + other.y)
        from .shapes import Point
        if isinstance(other, Point):
            return Point.temp(self.x + other.x, self.y + other.y)
        elif (isinstance(other, (tuple, list)) and len(other) == 2
              and type(other[0]) is not bool and type(other[1]) is not bool):
            try:
                return Vec2.temp(x=self.x + other[0], y=self.y + other[1])
            except OverflowError:       # ``v + (10**400, 0)`` (VB5)
                raise ValueError(_vec_overflow_message(other)) from None
            except TypeError:           # ``v + ("a", 1)``: Scena's words (VB13)
                raise TypeError(_vec_operand_message("add", other)) from None
        elif isinstance(other, Attribute):
            return self.__add__(other.value)     # a cell holding a pair, read fresh
        else:
            raise TypeError(_vec_operand_message("add", other))

    def __sub__(self, other):
        """
        Subtract another Vec2, tuple of floats, or Point from this vector.
        Args:
            other: Vec2, tuple of (float, float), or Point
        Returns:
            Vec2 when subtracting Vec2 or tuple, Point when subtracting Point
        """
        if isinstance(other, Vec2):
            return Vec2.temp(x=self.x - other.x, y=self.y - other.y)
        from .shapes import Point
        if isinstance(other, Point):
            return Point.temp(self.x - other.x, self.y - other.y)
        elif (isinstance(other, (tuple, list)) and len(other) == 2
              and type(other[0]) is not bool and type(other[1]) is not bool):
            try:
                return Vec2.temp(x=self.x - other[0], y=self.y - other[1])
            except OverflowError:       # ``v - (10**400, 0)`` (VB5)
                raise ValueError(_vec_overflow_message(other)) from None
            except TypeError:           # ``v - ("a", 1)``: Scena's words (VB13)
                raise TypeError(_vec_operand_message("subtract", other)) from None
        elif isinstance(other, Attribute):
            return self.__sub__(other.value)
        else:
            raise TypeError(_vec_operand_message("subtract", other))

    def __iadd__(self, other):
        """Implements the += operator for in-place addition."""
        self._refuse_author_write()
        d = self.__dict__
        bare = d.get('_scalar_bare_ok')
        if (bare is not None and bare.get('x') is True and bare.get('y') is True
                and not d.get('_field_anchors')):
            x0 = d.get('x', 0.0)    # what ScalarSlot.__get__ returns here (A3)
            y0 = d.get('y', 0.0)
            bare = True
        else:
            x0 = self.x
            y0 = self.y
            bare = False
        try:
            if isinstance(other, Vec2):
                x = x0 + other.x
                y = y0 + other.y
            elif (isinstance(other, (tuple, list)) and len(other) == 2
                  and type(other[0]) is not bool and type(other[1]) is not bool):
                x = x0 + other[0]
                y = y0 + other[1]
            else:
                from .shapes import Point
                if not isinstance(other, Point):
                    raise TypeError(_vec_operand_message("add", other))
                x = x0 + other.x
                y = y0 + other.y
        except OverflowError:
            raise ValueError(_vec_overflow_message(other)) from None
        except TypeError:               # ``v += ("a", 1)`` (VB13)
            raise TypeError(_vec_operand_message("add", other)) from None
        self._store_xy(x, y, bare)
        return self

    def __isub__(self, other):
        """Implements the -= operator for in-place subtraction."""
        self._refuse_author_write()
        d = self.__dict__
        bare = d.get('_scalar_bare_ok')
        if (bare is not None and bare.get('x') is True and bare.get('y') is True
                and not d.get('_field_anchors')):
            x0 = d.get('x', 0.0)    # what ScalarSlot.__get__ returns here (A3)
            y0 = d.get('y', 0.0)
            bare = True
        else:
            x0 = self.x
            y0 = self.y
            bare = False
        try:
            if isinstance(other, Vec2):
                x = x0 - other.x
                y = y0 - other.y
            elif (isinstance(other, (tuple, list)) and len(other) == 2
                  and type(other[0]) is not bool and type(other[1]) is not bool):
                x = x0 - other[0]
                y = y0 - other[1]
            else:
                from .shapes import Point
                if not isinstance(other, Point):
                    raise TypeError(_vec_operand_message("subtract", other))
                x = x0 - other.x
                y = y0 - other.y
        except OverflowError:
            raise ValueError(_vec_overflow_message(other)) from None
        except TypeError:               # ``v += ("a", 1)`` (VB13)
            raise TypeError(_vec_operand_message("subtract", other)) from None
        self._store_xy(x, y, bare)
        return self

    def _store_xy(self, x, y, bare: bool = False) -> None:
        """The one store of an in-place op (``+=``, ``-=``, ``do_rotation``):
        both axes are checked, then both are written. A batched axis write
        skips the field's finite check (``_coerce_magnitude_slot`` with
        ``clamp=True``): ``w += (inf, 0)`` stored inf while ``w.x = inf``
        raised, and ``ship.vel += (inf, 0)`` had written x when the vel setter
        refused. The batch also skips the Derivate guard: ``line.vec += …``
        on a Line(p1, p2) wrote a vector its p1 / p2 then disagreed with.
        ``bare``: the caller read x / y from ``__dict__`` because the A3 cache
        (``_scalar_bare_ok``) holds both as bare Defining leaves, so no
        Derivate walk is due; otherwise the caller's descriptor reads seeded
        the cache and it is read here. A part of a destroyed actor refuses at
        the x write (``ScalarSlot.__set__``), before either axis changes."""
        d = self.__dict__
        if not bare:
            cache = d.get('_scalar_bare_ok')
            if cache is None or cache.get('x') is not True or cache.get('y') is not True:
                self._refuse_derived_axes(x, y)
        if x.__class__ is not float or y.__class__ is not float or x - x != 0.0 or y - y != 0.0:
            # NaN / inf (finite: x - x == 0), or an int: ``w.x = 4`` keeps an
            # int, and ``4 + 10**400`` is an int no float holds whose
            # ``x - x`` is 0 (VB1). ``finite`` refuses both before either axis.
            from .validate import finite
            owner = d.get('_owner')
            field = d.get('_link_refused')      # ``ship.vel``: same words as its setter
            prefix = f"{owner.name}.{field} " if owner is not None and field else ""
            x = finite(x, prefix + "x")
            y = finite(y, prefix + "y")
        with self._batch_update():
            self.x = x
            self.y = y

    def _refuse_derived_axes(self, x, y) -> None:
        """The plain ``v.x = …`` Derivate refusal, for ``_store_xy``."""
        from .state import DerivedAttributeError
        der = self._derivate_source()
        for name, value in (('x', x), ('y', y)):
            if self._field_is_derivate(name):
                raise DerivedAttributeError(self._derived_field_message(name, "set", value))
            if der is not None:
                raise DerivedAttributeError(self._derived_refusal(der, "set", value, leaf=name))

    def __mul__(self, scalar: float) -> 'Vec2':
        """Scale by a number: ``v * 2``."""
        try:
            return Vec2.temp(x=self.x * scalar, y=self.y * scalar)
        except TypeError:
            raise TypeError(_vec_scale_message("*", scalar)) from None
        except OverflowError:
            raise ValueError(_vec_overflow_message(scalar)) from None

    def __truediv__(self, scalar: float) -> 'Vec2':
        """Divide by a number: ``v / 2``."""
        try:
            return Vec2.temp(x=self.x / scalar, y=self.y / scalar)
        except TypeError:
            raise TypeError(_vec_scale_message("/", scalar)) from None
        except OverflowError:
            raise ValueError(_vec_overflow_message(scalar)) from None

    def __neg__(self) -> 'Vec2':
        return Vec2.temp(x=-self.x, y=-self.y)

    def __iter__(self):
        """``x, y = v`` / ``tuple(v)``: the components now, as two floats (a
        value snapshot; the names do not follow the vector)."""
        return iter((float(self.x), float(self.y)))

    def __getitem__(self, key):
        # ``v["x"] @= …`` links a component; a number is not an index.
        if not isinstance(key, str):
            raise TypeError(_point_index_refusal(self, key))
        return Container.__getitem__(self, key)

    # Comparison operations
    # Value __eq__; mutable vector — not a dict/set key.
    __hash__ = None

    def __eq__(self, other: Union['Vec2', Tuple[float, float], Attribute]) -> bool:
        """
        Compare two Vec2 objects based on their x and y coordinates only.
        This is different from __eq__ which uses object identity.
        
        Args:
            other: Vec2 to compare with
            
        Returns:
            bool: True if x and y coordinates match, False otherwise
        """
        if isinstance(other, Vec2):
            return self.x == other.x and self.y == other.y
        elif isinstance(other, tuple) and len(other) == 2:
            return self.x == other[0] and self.y == other[1]
        elif getattr(type(other), "_point_eq_warns", False):
            return NotImplemented       # Point.__eq__ answers (and warns: PE1)
        else:
            return False

    # String representation
    def __repr__(self) -> str:
        return f"Vec2({self.x}, {self.y})"

    # Type conversion
    def to_tuple(self) -> Tuple[float, float]:
        """Convert to tuple representation."""
        return (self.x, self.y)

    def to_array(self) -> list[float]:
        """Convert to list representation."""
        return [self.x, self.y]

    # Ownership-tree leaf composite (x/y Defining; length/angle Derivate of self).
    # UpdateManager skips pass-through recalc when this node was written mid-cycle.
    _leaf_composite = True

    def _takein(self, new_value):
        """
        Take in a new value.
        Batches the part subtree so x/y writes do not each start a cycle.
        """
        if new_value is self:
            return
        if self.__dict__.get('_destroyed'):
            # A part of a destroyed actor (``held = ship.vel``): the raw store
            # below would skip ``ScalarSlot.__set__``'s refusal.
            from .entity import _refuse_if_destroyed
            _refuse_if_destroyed(self, "copy")

        # Nested under an outer no_update/batch_update: leaf writes already
        # skip update(); skip the redundant 3-node subtree walk.
        if self._in_batch_update:
            if self._takein_impl(new_value) and self.__dict__.get('_field_anchors'):
                from .state import _notify_source_anchors
                _notify_source_anchors(self)    # q["x"] @= v["x"] (S5-1)
            return

        previous_states: dict = {}
        self._push_batch_update_subtree(previous_states)
        try:
            changed = self._takein_impl(new_value)
        finally:
            self._restore_batch_update_subtree(previous_states)

        if changed:
            if self.__dict__.get('_field_anchors'):
                from .state import _notify_source_anchors
                _notify_source_anchors(self)    # q["x"] @= v["x"] (S5-1)
            self.update()

    def _takein_impl(self, other: Union['Vec2', tuple, list]) -> bool:
        """Assimilate values from another vector or tuple. Returns True if changed."""
        if isinstance(other, Attribute):
            other = other.value      # an st cell holding a Vec2 / (x, y): ``v << st.pos``
        overflow = False
        if isinstance(other, Vec2):
            x, y = float(other.x), float(other.y)
        elif (isinstance(other, (tuple, list)) and len(other) == 2
              and type(other[0]) is not bool and type(other[1]) is not bool
              and not isinstance(other[0], (str, bytes))
              and not isinstance(other[1], (str, bytes))):
            try:
                x = _as_coord(other[0])
                y = _as_coord(other[1])
            except OverflowError:
                overflow = True
        else:
            # Same reading and words as every point-like (a Point is a place).
            from .shapes import _xy_refusal
            raise TypeError("Vec2 << " + _xy_refusal(other, points=False))

        d = self.__dict__
        if overflow:
            # An int no float holds: Python's OverflowError, not a Scena one (GX15).
            r = repr(tuple(other))
            raise ValueError(f"a vector takes two finite numbers, got {r if len(r) <= 40 else r[:39] + '…'}")
        if x - x != 0.0 or y - y != 0.0:
            # Two finite numbers on every Vec2, as every other door says (VB4).
            # A part (``rect.vec``) took ``(0, inf)`` before GX15; a free vector
            # took NaN / inf through ``v << …`` and a pull until VB4, and no
            # consumer could read it (``_xy_of`` refuses it, arithmetic raises):
            # the error surfaced in a formula far from the write.
            from .shapes import _short_point
            raise ValueError(f"a vector takes two finite numbers, got {_short_point(other)}")
        old_x = d.get('x', 0.0)
        old_y = d.get('y', 0.0)
        if old_x != x or old_y != y:
            d['x'] = x
            d['y'] = y
            if d.get('_owner') is not None:
                # A part (``rect.vec``) is a pose input: this override skips the
                # funnel's bump (Container._takein), as Point's did (B1).
                bump_pose_rev(self)
            self._sync_computed()
            return True
        return False

    def _sync_computed(self) -> None:
        """Bring a computed length / angle in step with a raw x / y store.

        A pull stores through ``_takein_impl`` (a link on the whole vector) or
        ``ScalarAnchor._takein_impl`` (a link on one axis) without update()
        (Reactive Design, "Pull stores raw"); an owner's refresh then clears
        this node's dirty flag, so a stale value would stick. Computed = read
        once (``_derivate_state``) or written by ``_update_impl`` (in the
        dict; a value equal to the slot default is not stored).
        """
        d = self.__dict__
        computed = d.get('_derivate_state') or ()
        x = d.get('x', 0.0)
        y = d.get('y', 0.0)
        if 'length' in computed or 'length' in d:
            d['length'] = math.sqrt(x * x + y * y)
        if 'angle' in computed or 'angle' in d:
            d['angle'] = math.degrees(math.atan2(y, x))

    def reflect_about(self, normal: 'Vec2') -> 'Vec2':
        """
        Reflect this vector about a normal vector.
        Useful for collision responses and light calculations.
        """
        normal = _vec_arg(normal, "Vec2.reflect normal").normalize()
        return self - normal * 2 * self.dot(normal)

    def project_onto(self, onto: 'Vec2') -> 'Vec2':
        """
        Project this vector onto another vector.
        Useful for constraint satisfaction and collision resolution.
        """
        onto_normalized = _vec_arg(onto, "Vec2.project onto").normalize()
        return onto_normalized * self.dot(onto_normalized)

    def reject_from(self, from_vec: 'Vec2') -> 'Vec2':
        """
        Reject this vector from another vector (perpendicular component).
        Complement to project_onto().
        """
        return self - self.project_onto(from_vec)

    def clamp_length_to(self, min_length: float, max_length: float) -> 'Vec2':
        """
        Clamp this vector's length between min and max values.
        Useful for limiting forces, velocities, etc.
        """
        lo, hi = min_length, max_length
        if not ((lo.__class__ is float or (lo.__class__ is int and -1e308 < lo < 1e308))
                and (hi.__class__ is float or (hi.__class__ is int and -1e308 < hi < 1e308))):
            lo = _scalar_arg(min_length, "Vec2.clamp_length_to min_length")
            hi = _scalar_arg(max_length, "Vec2.clamp_length_to max_length")
        n = self.length
        if n == 0:
            return Vec2.temp()
        c = lo if lo > n else n         # max(n, lo), min(…, hi): their ties and NaN,
        c = hi if hi < c else c         # without two builtin calls
        return self * (c / n)

    # Self modifying methods -------------------------------------------------------------------------------------------------------

    def do_rotation(self, angle: float) -> None:
        """
        Rotate this vector by angle (in degrees), modifying itself.
        """
        from .validate import number
        rad = math.radians(number(angle, "Vec2.do_rotation angle"))
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        self._refuse_author_write()
        d = self.__dict__
        bare = d.get('_scalar_bare_ok')
        if (bare is not None and bare.get('x') is True and bare.get('y') is True
                and not d.get('_field_anchors')):
            x0 = d.get('x', 0.0)    # what ScalarSlot.__get__ returns here (A3)
            y0 = d.get('y', 0.0)
            bare = True
        else:
            x0 = self.x
            y0 = self.y
            bare = False
        x = x0 * cos_a - y0 * sin_a
        y = x0 * sin_a + y0 * cos_a
        self._store_xy(x, y, bare)


_object_new = object.__new__
_isfinite = math.isfinite

# What ``Vec2.temp`` leaves in a fresh vector's ``__dict__`` (ephemeral,
# ownerless, sealed), in the general constructor's key order. ``_scena_system``,
# ``_parts`` (a fresh ContainerSet each), ``x`` and ``y`` are filled per call.
_TEMP_STATE = {
    '_node_id': None, '_ephemeral': True, '_scena_system': None, '_owner': None,
    '_parts': None, '_attr_name': 'vec2', '_name': 'vec2',
    '_in_batch_update': False, '_dirty': False, '_resolving': False, '_link': None,
    '_field_type': FieldType.Defining, '_derivate_live': False,
    '_needs_pull_invalidate': False, 'x': 0.0, 'y': 0.0, _SEALED: True,
}


# Standalone methods -------------------------------------------------------------------------------------------------------

def _as_xy(point) -> Tuple[float, float]:
    """Bare (x, y) from a point-like: the one reading (``shapes._xy_of``)."""
    from .shapes import _xy_of
    return _xy_of(point, required=True)


def chance(p) -> bool:
    """Return True with probability ``p`` (0 = never, 1 = always).

    ``p`` is a fraction in ``[0, 1]``. ``chance(0.30)`` is a 30% roll.
    """
    if _SOLVER_READING:
        refuse_if_solver_reading('chance()')
    return random.random() < _chance_probability(p, "chance")


def _chance_probability(p, what: str = "chance") -> float:
    """``p`` as a probability in ``[0, 1]``, or raise naming ``what(0.30)``.

    Shared by the global ``chance`` and ``slot.chance`` (Endless).
    """
    from .validate import finite
    shown = as_payload(p)
    try:
        p = finite(shown, f"{what}()")
        if callable(p):
            raise TypeError(f"{what}() expected a number, got a function")
    except TypeError:
        raise TypeError(
            f"{what}() takes a probability from 0 to 1, got {shown!r}. "
            f"Write {what}(0.30) for 30%."
        ) from None
    if p != p or p < 0.0 or p > 1.0:
        hint = (
            f" That looks like a percent — write {what}({p / 100:.2f})."
            if 1.0 < p <= 100.0 else f" Write {what}(0.30) for 30%."
        )
        raise ValueError(
            f"{what}() takes a probability from 0 to 1, got {shown!r}.{hint}"
        )
    return float(p)


def vec_from_angle(angle: float, length: float = 1.0, reference_vec: Optional[Vec2] = None) -> Vec2:
    """Create a vector from an angle (degrees) and length.

    Args:
        angle: Degrees (0 = +x, counter-clockwise).
        length: Vector length (default 1).
        reference_vec: Measure ``angle`` from this vector's direction instead of +x.
    """
    from .validate import number
    angle = number(angle, "vec_from_angle angle")
    length = number(length, "vec_from_angle length")
    if reference_vec is not None:
        # If reference vector is provided, add its angle to get the absolute angle
        ref_angle = _vec_arg(reference_vec, "vec_from_angle reference_vec").angle
        absolute_angle = ref_angle + angle
    else:
        # If no reference vector, use angle directly (relative to x-axis)
        absolute_angle = angle

    rad = math.radians(absolute_angle)
    return Vec2.temp(
        x=length * math.cos(rad),
        y=length * math.sin(rad)
    )



# The Vec2 a State cell holds refuses an in-place author write (``st.pos.x = 5``):
# ``state._rehold_payload`` installs the guard; see ``state._HELD_BY_VALUE``.
from . import state as _state  # noqa: E402
_state._HELD_BY_VALUE = Vec2
