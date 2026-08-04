# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""Experimental versioned array expressions scoped to a scientific-array owner prim.

Authored expressions are parsed with Python's AST parser, but only the explicit
version-1 array-expression language is accepted. Authored text is never passed to
``eval`` or ``exec``.
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass

import warp as wp
import warp_simdata as simdata
from omni.cae.core import cache, usd_utils
from omni.cae.schema import cae
from pxr import OmniSci, Sdf, Usd

LANGUAGE_VERSION = 1
_IF_ALIAS = "_i"

_FUNCTION_ARITIES = {
    "ge": 2,
    "gt": 2,
    "le": 2,
    "lt": 2,
    "eq": 2,
    "ne": 2,
    "where": 3,
    "abs": 1,
    "sqrt": 1,
    "exp": 1,
    "log": 1,
    "sin": 1,
    "cos": 1,
    "floor": 1,
    "ceil": 1,
    "min": 2,
    "max": 2,
    "pow": 2,
    "clamp": 3,
    "vec2": 2,
    "vec3": 3,
    "vec4": 4,
    "component": 2,
    "magnitude": 1,
    "dot": 2,
    "cross": 2,
    "zeros_like": 1,
    "ones_like": 1,
    "full_like": 2,
}
_FUNCTIONS = set(_FUNCTION_ARITIES)
_PARSED_FUNCTIONS = _FUNCTIONS | {_IF_ALIAS}
_COMPARISON_OPS = {"ge": 4, "gt": 5, "le": 6, "lt": 7, "eq": 8, "ne": 9}
_BINARY_OPS = {ast.Add: 0, ast.Sub: 1, ast.Mult: 2, ast.Div: 3, ast.Pow: 12}
_BINARY_FUNCTION_OPS = {"min": 10, "max": 11, "pow": 12}
_UNARY_FUNCTION_OPS = {
    "abs": 0,
    "sqrt": 1,
    "exp": 2,
    "log": 3,
    "sin": 4,
    "cos": 5,
    "floor": 6,
    "ceil": 7,
}
_VIRTUAL_VALUE_MARKER = "caeArrayExpression"


@dataclass(frozen=True)
class ArrayExpressionDiagnostic:
    """An authoring-oriented expression diagnostic with source location."""

    code: str
    message: str
    line: int = 1
    column: int = 1
    end_column: int | None = None

    def format(self) -> str:
        return f"{self.code} at {self.line}:{self.column}: {self.message}"


class ArrayExpressionError(ValueError):
    """Raised when an authored expression cannot be analyzed or evaluated."""

    def __init__(self, diagnostic: ArrayExpressionDiagnostic):
        super().__init__(diagnostic.format())
        self.diagnostic = diagnostic


class ArrayExpressionValueProvider:
    """Expose enabled array expressions through raw-array materialization."""

    def can_handle(self, prim: Usd.Prim, instance_name: str) -> bool:
        return has_array_expression(prim, instance_name)

    def resolve(self, request):
        native_fields = local_native_fields(request.prim)
        resolver = create_array_value_resolver(
            request.prim,
            native_names={field.name for field in native_fields},
            time_code=request.time_code,
        )
        return resolver(request)

    def get_time_samples(self, prim: Usd.Prim, instance_name: str) -> tuple[float, ...]:
        from .array_values import get_array_time_samples

        native_fields = local_native_fields(prim)
        descriptions = {
            description.name: description for description in describe_array_expressions(prim, native_fields)
        }
        description = descriptions.get(instance_name)
        if description is None or not description.valid:
            return ()

        samples = {
            sample for dependency in description.dependencies for sample in get_array_time_samples(prim, dependency)
        }
        return tuple(sorted(samples))


@dataclass(frozen=True)
class ArrayExpressionDescription:
    name: str
    display_name: str
    expression: str
    compute_device: str
    enabled: bool
    language_version: int
    dependencies: tuple[str, ...]
    association: simdata.AssociationType | None
    canonical_expression: str
    diagnostics: tuple[ArrayExpressionDiagnostic, ...]

    @property
    def valid(self) -> bool:
        return self.enabled and not self.diagnostics


@dataclass(frozen=True)
class _Definition:
    expression: str
    display_name: str
    compute_device: str
    enabled: bool
    language_version: int


@dataclass(frozen=True)
class _LocalField:
    name: str
    label: str
    association: simdata.AssociationType


def _definitions(prim: Usd.Prim) -> dict[str, _Definition]:
    result = {}
    for name in usd_utils.get_instances(prim, "CaeArrayExpressionAPI"):
        api = cae.ArrayExpressionAPI(prim, name)
        expression = api.GetExpressionAttr().Get() or ""
        display_name = api.GetDisplayNameAttr().Get() or name
        compute_device = str(api.GetComputeDeviceAttr().Get() or "auto")
        enabled = bool(api.GetEnabledAttr().Get())
        authored_version = api.GetLanguageVersionAttr().Get()
        language_version = int(LANGUAGE_VERSION if authored_version is None else authored_version)
        result[name] = _Definition(expression, display_name, compute_device, enabled, language_version)
    return result


def has_array_expression(prim: Usd.Prim, name: str) -> bool:
    return name in _definitions(prim)


def array_expression_prims(prim: Usd.Prim, names: set[str] | None = None) -> list[Usd.Prim]:
    """Find expression owners in the adapter scope surrounding *prim*.

    Expression semantics remain prim-local. This search only bridges an
    operator's dataset entry prim to nearby scientific-array owner prims, such
    as CGNS ``FlowSolution`` children.
    """

    def owned_names(candidate: Usd.Prim) -> set[str]:
        definitions = _definitions(candidate)
        companions = {
            name
            for name in usd_utils.get_instances(candidate, "OmniSciFieldAPI")
            if is_array_expression_companion(candidate, name)
        }
        return set(definitions) | companions

    def matches(candidate: Usd.Prim) -> bool:
        owned = owned_names(candidate)
        return bool(owned and (names is None or names.intersection(owned)))

    # A directly requested owner prim is authoritative. Do not let unrelated
    # sibling datasets with the same expression name make this request
    # ambiguous.
    if matches(prim):
        return [prim]

    root = prim.GetParent() if prim.GetParent() else prim
    result = []
    for candidate in Usd.PrimRange(root):
        if candidate != prim and matches(candidate):
            result.append(candidate)
    return result


def local_native_fields(prim: Usd.Prim) -> list[_LocalField]:
    """Describe authored OmniSci fields owned by *prim*, excluding expressions."""
    associations = {
        "node": simdata.AssociationType.NODE,
        "element": simdata.AssociationType.ELEMENT,
        "none": simdata.AssociationType.NOT_SPECIFIED,
    }
    fields = []
    for name in usd_utils.get_instances(prim, "OmniSciFieldAPI"):
        if is_array_expression_companion(prim, name):
            continue
        api = OmniSci.FieldAPI(prim, name)
        association = associations.get(str(api.GetAssociationAttr().Get()))
        if association is None:
            continue
        fields.append(_LocalField(name, str(api.GetNameAttr().Get() or name), association))
    return fields


def _value_attr_name(name: str) -> str:
    return f"omni:sci:array:{name}:value"


def is_array_expression_companion(prim: Usd.Prim, name: str) -> bool:
    """Return whether field metadata was authored for a virtual expression value."""
    attr = prim.GetAttribute(_value_attr_name(name))
    return bool(attr and attr.GetCustomData().get(_VIRTUAL_VALUE_MARKER, False))


def remove_array_expression_companion(prim: Usd.Prim, name: str) -> None:
    """Remove runtime field/array metadata previously authored for an expression."""
    if not is_array_expression_companion(prim, name):
        return
    field_api = OmniSci.FieldAPI(prim, name)
    for attr in (field_api.GetNameAttr(), field_api.GetAssociationAttr()):
        if attr:
            prim.RemoveProperty(attr.GetName())
    prim.RemoveProperty(_value_attr_name(name))
    prim.RemoveAPI("OmniSciFieldAPI", name)
    prim.RemoveAPI("OmniSciArrayAPI", name)


def _native_component_counts(prim: Usd.Prim) -> dict[str, int]:
    """Return component widths for native scientific arrays owned by *prim*."""
    vector_widths = {
        Sdf.ValueTypeNames.Float2Array: 2,
        Sdf.ValueTypeNames.Float3Array: 3,
        Sdf.ValueTypeNames.Float4Array: 4,
    }
    counts = {}
    for name in usd_utils.get_instances(prim, "OmniSciArrayAPI"):
        if is_array_expression_companion(prim, name):
            continue
        value_attr = prim.GetAttribute(_value_attr_name(name))
        counts[name] = vector_widths.get(value_attr.GetTypeName(), 1) if value_attr else 1
    return counts


def _component_count(
    name: str,
    definitions: dict[str, _Definition],
    native_counts: dict[str, int],
    visiting: tuple[str, ...] = (),
) -> int:
    if name not in definitions:
        return native_counts.get(name, 1)
    if name in visiting:
        return 1
    definition = definitions[name]
    tree = _parse(definition.expression, definition.language_version)

    def resolve_node(node: ast.AST) -> int:
        if isinstance(node, ast.Name):
            return _component_count(node.id, definitions, native_counts, (*visiting, name))
        if isinstance(node, ast.Constant):
            return 1
        if isinstance(node, ast.UnaryOp):
            return resolve_node(node.operand)
        if isinstance(node, ast.BinOp):
            return max(resolve_node(node.left), resolve_node(node.right))
        if isinstance(node, ast.Call):
            function_name = "where" if node.func.id == _IF_ALIAS else node.func.id
            if function_name in {"zeros_like", "ones_like", "full_like"}:
                return resolve_node(node.args[0])
            if function_name in {"vec2", "vec3", "vec4"}:
                return int(function_name[-1])
            if function_name == "cross":
                return 3
            if function_name in {"component", "magnitude", "dot"}:
                return 1
            return max(resolve_node(arg) for arg in node.args)
        return 1

    return resolve_node(tree.body)


def sync_array_expression_companions(
    prim: Usd.Prim,
    descriptions: list[ArrayExpressionDescription],
    names: list[str] | None = None,
) -> None:
    """Synchronize virtual OmniSci metadata with current prim-local expressions."""
    descriptions_by_name = {item.name: item for item in descriptions}
    valid_names = {item.name for item in descriptions if item.valid}
    for name in usd_utils.get_instances(prim, "OmniSciFieldAPI"):
        if is_array_expression_companion(prim, name) and name not in valid_names:
            remove_array_expression_companion(prim, name)

    requested_names = sorted(valid_names) if names is None else names
    definitions = _definitions(prim)
    native_counts = _native_component_counts(prim)
    value_types = {
        1: Sdf.ValueTypeNames.FloatArray,
        2: Sdf.ValueTypeNames.Float2Array,
        3: Sdf.ValueTypeNames.Float3Array,
        4: Sdf.ValueTypeNames.Float4Array,
    }
    association_tokens = {
        simdata.AssociationType.NODE: "node",
        simdata.AssociationType.ELEMENT: "element",
        simdata.AssociationType.NOT_SPECIFIED: "none",
    }
    for name in requested_names:
        description = descriptions_by_name.get(name)
        if description is None:
            raise _diagnostic("E_UNKNOWN_FIELD", f"unknown derived field '{name}'")
        if not description.valid:
            diagnostic = (
                description.diagnostics[0]
                if description.diagnostics
                else ArrayExpressionDiagnostic("E_DISABLED_DEPENDENCY", f"derived field '{name}' is disabled")
            )
            raise ArrayExpressionError(diagnostic)

        field_api = OmniSci.FieldAPI.Apply(prim, name)
        field_api.CreateNameAttr(description.display_name or name)
        field_api.CreateAssociationAttr(association_tokens[description.association])
        OmniSci.ArrayAPI.Apply(prim, name)

        value_type = value_types[_component_count(name, definitions, native_counts)]
        value_attr = prim.GetAttribute(_value_attr_name(name))
        if value_attr and value_attr.GetTypeName() != value_type:
            if not is_array_expression_companion(prim, name):
                raise _diagnostic("E_COLLISION", f"an array named '{name}' already exists")
            prim.RemoveProperty(value_attr.GetName())
            value_attr = None
        if not value_attr:
            value_attr = prim.CreateAttribute(_value_attr_name(name), value_type)
        custom_data = value_attr.GetCustomData()
        custom_data[_VIRTUAL_VALUE_MARKER] = True
        value_attr.SetCustomData(custom_data)


def _diagnostic(
    code: str, message: str, node: ast.AST | None = None, *, column: int | None = None
) -> ArrayExpressionError:
    line = getattr(node, "lineno", 1) if node is not None else 1
    source_column = column if column is not None else getattr(node, "col_offset", 0) + 1
    end_column = getattr(node, "end_col_offset", None) if node is not None else None
    return ArrayExpressionError(ArrayExpressionDiagnostic(code, message, line, source_column, end_column))


def _parse(expression: str, language_version: int = LANGUAGE_VERSION) -> ast.Expression:
    if language_version != LANGUAGE_VERSION:
        raise _diagnostic(
            "E_VERSION",
            f"unsupported expression language version {language_version}; expected {LANGUAGE_VERSION}",
        )
    # ``if`` is part of the language but a Python keyword. Replace only the two
    # identifier characters so AST source columns still refer to authored text.
    normalized = re.sub(r"\bif(?=\s*\()", _IF_ALIAS, expression)
    if not normalized.strip():
        raise _diagnostic("E_EMPTY", "expression is empty")
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise ArrayExpressionError(
            ArrayExpressionDiagnostic("E_SYNTAX", exc.msg, exc.lineno or 1, exc.offset or 1)
        ) from exc
    _validate_node(tree.body)
    return tree


def _validate_node(node: ast.AST) -> None:
    if isinstance(node, ast.Name):
        return
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and not isinstance(node.value, bool):
        return
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPS:
        _validate_node(node.left)
        _validate_node(node.right)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        _validate_node(node.operand)
        return
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _PARSED_FUNCTIONS:
        function_name = "where" if node.func.id == _IF_ALIAS else node.func.id
        expected = _FUNCTION_ARITIES[function_name]
        if node.keywords or len(node.args) != expected:
            raise _diagnostic(
                "E_ARITY",
                f"{function_name} expects exactly {expected} positional arguments",
                node,
            )
        if function_name == "component" and not (
            isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, int)
            and 0 <= node.args[1].value <= 3
        ):
            raise _diagnostic(
                "E_COMPONENT_INDEX",
                "component index must be an integer literal from 0 through 3",
                node.args[1],
            )
        if function_name == "full_like" and _numeric_literal(node.args[1]) is None:
            raise _diagnostic(
                "E_FILL_VALUE",
                "full_like fill value must be a numeric literal",
                node.args[1],
            )
        for arg in node.args:
            _validate_node(arg)
        return
    raise _diagnostic(
        "E_UNSUPPORTED",
        f"unsupported expression construct: {ast.dump(node, include_attributes=False)}",
        node,
    )


def _dependencies(tree: ast.Expression) -> set[str]:
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id not in _PARSED_FUNCTIONS}


def _numeric_literal(node: ast.AST) -> float | None:
    """Return a signed numeric literal, or None for a computed expression."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        value = _numeric_literal(node.operand)
        if value is not None:
            return -value if isinstance(node.op, ast.USub) else value
    return None


def describe_array_expressions(prim: Usd.Prim, native_fields: list) -> list[ArrayExpressionDescription]:
    """Analyze every authored expression without loading array values."""
    native_by_name = {field.name: field for field in native_fields}
    definitions = _definitions(prim)
    resolved = dict(native_by_name)
    resolving: list[str] = []
    analyzed: dict[str, ArrayExpressionDescription] = {}

    def resolve(name: str):
        if name in resolved:
            return resolved[name]
        if name not in definitions:
            raise _diagnostic("E_UNKNOWN_FIELD", f"unknown field '{name}'")
        if name in resolving:
            cycle = " -> ".join([*resolving[resolving.index(name) :], name])
            raise _diagnostic("E_CYCLE", f"cyclic derived-field dependency: {cycle}")
        resolving.append(name)
        definition = definitions[name]
        if not definition.enabled:
            raise _diagnostic("E_DISABLED_DEPENDENCY", f"derived field '{name}' is disabled")
        tree = _parse(definition.expression, definition.language_version)
        dependencies = _dependencies(tree)
        if not dependencies:
            raise _diagnostic(
                "E_NO_DEPENDENCY",
                "a derived field must reference at least one field on the same prim",
                tree.body,
            )
        dependency_fields = []
        for dependency in sorted(dependencies):
            try:
                dependency_fields.append(resolve(dependency))
            except ArrayExpressionError as exc:
                if exc.diagnostic.code == "E_UNKNOWN_FIELD":
                    node = next(
                        candidate
                        for candidate in ast.walk(tree)
                        if isinstance(candidate, ast.Name) and candidate.id == dependency
                    )
                    raise _diagnostic("E_UNKNOWN_FIELD", f"unknown field '{dependency}'", node) from exc
                raise
        associations = {field.association for field in dependency_fields}
        if len(associations) != 1:
            raise _diagnostic(
                "E_ASSOCIATION",
                "all expression dependencies must have the same field association",
                tree.body,
            )
        association = associations.pop()
        result = type("ResolvedExpression", (), {"name": name, "association": association})()
        resolving.pop()
        resolved[name] = result
        analyzed[name] = ArrayExpressionDescription(
            name=name,
            display_name=definition.display_name,
            expression=definition.expression,
            compute_device=definition.compute_device,
            enabled=True,
            language_version=definition.language_version,
            dependencies=tuple(sorted(dependencies)),
            association=association,
            canonical_expression=ast.dump(tree, annotate_fields=True, include_attributes=False),
            diagnostics=(),
        )
        return result

    descriptions = []
    for name, definition in definitions.items():
        if name in native_by_name:
            descriptions.append(
                ArrayExpressionDescription(
                    name,
                    definition.display_name,
                    definition.expression,
                    definition.compute_device,
                    definition.enabled,
                    definition.language_version,
                    (),
                    None,
                    "",
                    (
                        ArrayExpressionDiagnostic(
                            "E_COLLISION",
                            f"a native field named '{name}' already exists",
                        ),
                    ),
                )
            )
            continue
        if not definition.enabled:
            descriptions.append(
                ArrayExpressionDescription(
                    name,
                    definition.display_name,
                    definition.expression,
                    definition.compute_device,
                    False,
                    definition.language_version,
                    (),
                    None,
                    "",
                    (),
                )
            )
            continue
        try:
            resolve(name)
            descriptions.append(analyzed[name])
        except ArrayExpressionError as exc:
            if name in resolving:
                resolving.clear()
            tree = None
            try:
                tree = _parse(definition.expression, definition.language_version)
            except ArrayExpressionError:
                pass
            descriptions.append(
                ArrayExpressionDescription(
                    name,
                    definition.display_name,
                    definition.expression,
                    definition.compute_device,
                    True,
                    definition.language_version,
                    tuple(sorted(_dependencies(tree))) if tree else (),
                    None,
                    ast.dump(tree, annotate_fields=True, include_attributes=False) if tree else "",
                    (exc.diagnostic,),
                )
            )
    return descriptions


@simdata.cached
def _get_materialize_kernel(field_model: simdata.FieldModel):
    @simdata.kernel(module="unique")
    @simdata.utils.set_qualname("omni_cae_materialize_expression_input")
    def materialize(field: field_model.FieldHandle, output: wp.array(dtype=wp.float32)):
        index = wp.tid()
        output[index] = wp.float32(field_model.FieldAPI.get(field, index))

    return materialize


@wp.kernel(enable_backward=False, module="unique")
def _binary_kernel(
    left: wp.array(dtype=wp.float32),
    right: wp.array(dtype=wp.float32),
    output: wp.array(dtype=wp.float32),
    opcode: wp.int32,
):
    index = wp.tid()
    lhs = left[index]
    rhs = right[index]
    if opcode == 0:
        output[index] = lhs + rhs
    elif opcode == 1:
        output[index] = lhs - rhs
    elif opcode == 2:
        output[index] = lhs * rhs
    elif opcode == 3:
        output[index] = lhs / rhs
    elif opcode == 4:
        output[index] = wp.float32(lhs >= rhs)
    elif opcode == 5:
        output[index] = wp.float32(lhs > rhs)
    elif opcode == 6:
        output[index] = wp.float32(lhs <= rhs)
    elif opcode == 7:
        output[index] = wp.float32(lhs < rhs)
    elif opcode == 8:
        output[index] = wp.float32(lhs == rhs)
    elif opcode == 9:
        output[index] = wp.float32(lhs != rhs)
    elif opcode == 10:
        output[index] = wp.min(lhs, rhs)
    elif opcode == 11:
        output[index] = wp.max(lhs, rhs)
    else:
        output[index] = wp.pow(lhs, rhs)


@wp.kernel(enable_backward=False, module="unique")
def _negate_kernel(value: wp.array(dtype=wp.float32), output: wp.array(dtype=wp.float32)):
    index = wp.tid()
    output[index] = -value[index]


@wp.kernel(enable_backward=False, module="unique")
def _unary_function_kernel(
    value: wp.array(dtype=wp.float32),
    output: wp.array(dtype=wp.float32),
    opcode: wp.int32,
):
    index = wp.tid()
    item = value[index]
    if opcode == 0:
        output[index] = wp.abs(item)
    elif opcode == 1:
        output[index] = wp.sqrt(item)
    elif opcode == 2:
        output[index] = wp.exp(item)
    elif opcode == 3:
        output[index] = wp.log(item)
    elif opcode == 4:
        output[index] = wp.sin(item)
    elif opcode == 5:
        output[index] = wp.cos(item)
    elif opcode == 6:
        output[index] = wp.floor(item)
    else:
        output[index] = wp.ceil(item)


@wp.kernel(enable_backward=False, module="unique")
def _clamp_kernel(
    value: wp.array(dtype=wp.float32),
    minimum: wp.array(dtype=wp.float32),
    maximum: wp.array(dtype=wp.float32),
    output: wp.array(dtype=wp.float32),
):
    index = wp.tid()
    output[index] = wp.clamp(value[index], minimum[index], maximum[index])


@wp.kernel(enable_backward=False, module="unique")
def _where_kernel(
    condition: wp.array(dtype=wp.float32),
    when_true: wp.array(dtype=wp.float32),
    when_false: wp.array(dtype=wp.float32),
    output: wp.array(dtype=wp.float32),
):
    index = wp.tid()
    output[index] = when_true[index] if condition[index] != 0.0 else when_false[index]


def _materialize(field: simdata.Field) -> wp.array:
    if simdata.utils.get_vector_length(field.dtype) != 1:
        raise ValueError(f"expected a scalar field, got {field.dtype}")
    output = wp.empty(field.size, dtype=wp.float32, device=field.device)
    kernel = _get_materialize_kernel(field.field_model)
    wp.launch(kernel, dim=field.size, inputs=[field.handle, output], device=field.device)
    return output


def _materialize_value(field: simdata.Field):
    component_count = simdata.utils.get_vector_length(field.dtype)
    if component_count == 1:
        return _materialize(field)
    return [_materialize(simdata.Field.from_field(field, component=index)) for index in range(component_count)]


def _device_alias(device) -> str:
    try:
        return wp.get_device(device).alias
    except Exception as exc:
        raise ValueError(f"compute device '{device}' is not available") from exc


def _as_components(value) -> list[wp.array]:
    return value if isinstance(value, list) else [value]


def _broadcast_values(left, right, node: ast.AST):
    left_components = _as_components(left)
    right_components = _as_components(right)
    if len(left_components) == 1 and len(right_components) > 1:
        left_components *= len(right_components)
    elif len(right_components) == 1 and len(left_components) > 1:
        right_components *= len(left_components)
    if len(left_components) != len(right_components):
        raise _diagnostic(
            "E_VECTOR_LENGTH",
            f"vector lengths {len(left_components)} and {len(right_components)} are incompatible",
            node,
        )
    return left_components, right_components


def _binary_value(left, right, opcode: int, size: int, device: str, node: ast.AST):
    left_components, right_components = _broadcast_values(left, right, node)
    outputs = []
    for lhs, rhs in zip(left_components, right_components):
        output = wp.empty(size, dtype=wp.float32, device=device)
        wp.launch(_binary_kernel, dim=size, inputs=[lhs, rhs, output, opcode], device=device)
        outputs.append(output)
    return outputs[0] if len(outputs) == 1 else outputs


def _unary_value(value, opcode: int, size: int, device: str):
    outputs = []
    for component in _as_components(value):
        output = wp.empty(size, dtype=wp.float32, device=device)
        wp.launch(
            _unary_function_kernel,
            dim=size,
            inputs=[component, output, opcode],
            device=device,
        )
        outputs.append(output)
    return outputs[0] if len(outputs) == 1 else outputs


def _constant_like(value, fill_value: float, size: int, device: str):
    """Create a scalar or vector constant with the same component layout as *value*."""
    outputs = [wp.full(size, fill_value, dtype=wp.float32, device=device) for _ in _as_components(value)]
    return outputs[0] if len(outputs) == 1 else outputs


def _evaluate_node(node: ast.AST, inputs: dict[str, object], size: int, device: str):
    if isinstance(node, ast.Name):
        return inputs[node.id]
    if isinstance(node, ast.Constant):
        return wp.full(size, float(node.value), dtype=wp.float32, device=device)
    if isinstance(node, ast.UnaryOp):
        value = _evaluate_node(node.operand, inputs, size, device)
        if isinstance(node.op, ast.UAdd):
            return value
        outputs = []
        for component in _as_components(value):
            output = wp.empty(size, dtype=wp.float32, device=device)
            wp.launch(_negate_kernel, dim=size, inputs=[component, output], device=device)
            outputs.append(output)
        return outputs[0] if len(outputs) == 1 else outputs
    if isinstance(node, ast.BinOp):
        left = _evaluate_node(node.left, inputs, size, device)
        right = _evaluate_node(node.right, inputs, size, device)
        return _binary_value(left, right, _BINARY_OPS[type(node.op)], size, device, node)
    if isinstance(node, ast.Call):
        function_name = "where" if node.func.id == _IF_ALIAS else node.func.id
        if function_name in {"zeros_like", "ones_like", "full_like"}:
            reference = _evaluate_node(node.args[0], inputs, size, device)
            if function_name == "zeros_like":
                fill_value = 0.0
            elif function_name == "ones_like":
                fill_value = 1.0
            else:
                fill_value = _numeric_literal(node.args[1])
                assert fill_value is not None
            return _constant_like(reference, fill_value, size, device)
        if function_name == "component":
            value = _evaluate_node(node.args[0], inputs, size, device)
            if not isinstance(value, list):
                raise _diagnostic(
                    "E_VECTOR_ARGUMENT",
                    "component expects a vector value",
                    node.args[0],
                )
            components = _as_components(value)
            component_index = node.args[1].value
            if component_index >= len(components):
                raise _diagnostic(
                    "E_COMPONENT_INDEX",
                    f"component index {component_index} is out of range for a {len(components)}-component value",
                    node.args[1],
                )
            return components[component_index]

        args = [_evaluate_node(arg, inputs, size, device) for arg in node.args]
        if function_name in {"vec2", "vec3", "vec4"}:
            if any(isinstance(arg, list) for arg in args):
                raise _diagnostic(
                    "E_VECTOR_ARGUMENT",
                    f"{function_name} arguments must be scalar",
                    node,
                )
            return args
        if function_name == "magnitude":
            components = _as_components(args[0])
            squared = [_binary_value(item, item, 2, size, device, node) for item in components]
            total = squared[0]
            for item in squared[1:]:
                total = _binary_value(total, item, 0, size, device, node)
            return _unary_value(total, _UNARY_FUNCTION_OPS["sqrt"], size, device)
        if function_name == "dot":
            if not isinstance(args[0], list) or not isinstance(args[1], list):
                raise _diagnostic("E_VECTOR_ARGUMENT", "dot expects vector arguments", node)
            left, right = _broadcast_values(args[0], args[1], node)
            products = [_binary_value(lhs, rhs, 2, size, device, node) for lhs, rhs in zip(left, right)]
            result = products[0]
            for item in products[1:]:
                result = _binary_value(result, item, 0, size, device, node)
            return result
        if function_name == "cross":
            if not isinstance(args[0], list) or not isinstance(args[1], list):
                raise _diagnostic("E_VECTOR_ARGUMENT", "cross expects vector arguments", node)
            left, right = _broadcast_values(args[0], args[1], node)
            if len(left) != 3:
                raise _diagnostic(
                    "E_VECTOR_ARGUMENT",
                    "cross expects two three-component vectors",
                    node,
                )
            return [
                _binary_value(
                    _binary_value(left[1], right[2], 2, size, device, node),
                    _binary_value(left[2], right[1], 2, size, device, node),
                    1,
                    size,
                    device,
                    node,
                ),
                _binary_value(
                    _binary_value(left[2], right[0], 2, size, device, node),
                    _binary_value(left[0], right[2], 2, size, device, node),
                    1,
                    size,
                    device,
                    node,
                ),
                _binary_value(
                    _binary_value(left[0], right[1], 2, size, device, node),
                    _binary_value(left[1], right[0], 2, size, device, node),
                    1,
                    size,
                    device,
                    node,
                ),
            ]
        if function_name == "where":
            condition = args[0]
            if isinstance(condition, list):
                raise _diagnostic("E_VECTOR_CONDITION", "where condition must be scalar", node.args[0])
            when_true, when_false = _broadcast_values(args[1], args[2], node)
            outputs = []
            for true_component, false_component in zip(when_true, when_false):
                output = wp.empty(size, dtype=wp.float32, device=device)
                wp.launch(
                    _where_kernel,
                    dim=size,
                    inputs=[condition, true_component, false_component, output],
                    device=device,
                )
                outputs.append(output)
            return outputs[0] if len(outputs) == 1 else outputs
        elif function_name == "clamp":
            values, minima = _broadcast_values(args[0], args[1], node)
            values, maxima = _broadcast_values(values, args[2], node)
            minima, values = _broadcast_values(minima, values, node)
            outputs = []
            for value, minimum, maximum in zip(values, minima, maxima):
                output = wp.empty(size, dtype=wp.float32, device=device)
                wp.launch(
                    _clamp_kernel,
                    dim=size,
                    inputs=[value, minimum, maximum, output],
                    device=device,
                )
                outputs.append(output)
            return outputs[0] if len(outputs) == 1 else outputs
        elif function_name in _UNARY_FUNCTION_OPS:
            return _unary_value(args[0], _UNARY_FUNCTION_OPS[function_name], size, device)
        elif function_name in _BINARY_FUNCTION_OPS:
            return _binary_value(
                args[0],
                args[1],
                _BINARY_FUNCTION_OPS[function_name],
                size,
                device,
                node,
            )
        else:
            return _binary_value(args[0], args[1], _COMPARISON_OPS[function_name], size, device, node)
    raise AssertionError(f"validated expression contains unexpected node {node!r}")


def create_array_value_resolver(
    prim: Usd.Prim,
    *,
    native_names: set[str] | None = None,
    time_code: Usd.TimeCode = Usd.TimeCode.Default(),
):
    """Create a resolver that evaluates expressions in raw scientific-array layout."""
    definitions = _definitions(prim)
    native_names = native_names or set()
    native_counts = _native_component_counts(prim)

    def graph_signature(field_name: str, visiting: tuple[str, ...] = ()) -> tuple:
        if field_name not in definitions:
            return ("native", field_name)
        if field_name in native_names:
            raise _diagnostic("E_COLLISION", f"a native field named '{field_name}' already exists")
        if field_name in visiting:
            cycle = " -> ".join((*visiting[visiting.index(field_name) :], field_name))
            raise _diagnostic("E_CYCLE", f"cyclic derived-field dependency: {cycle}")
        definition = definitions[field_name]
        if not definition.enabled:
            raise _diagnostic("E_DISABLED_DEPENDENCY", f"derived field '{field_name}' is disabled")
        tree = _parse(definition.expression, definition.language_version)
        dependencies = tuple(sorted(_dependencies(tree)))
        return (
            "derived",
            field_name,
            definition.language_version,
            definition.compute_device,
            ast.dump(tree, annotate_fields=True, include_attributes=False),
            tuple(graph_signature(dependency, (*visiting, field_name)) for dependency in dependencies),
        )

    def expression_cache_key(field_name: str, target_device: str) -> str:
        signature = repr(graph_signature(field_name)).encode("utf-8")
        digest = hashlib.sha256(signature).hexdigest()
        root_identifier = prim.GetStage().GetRootLayer().identifier
        return (
            f"[simdata:ArrayExpression:v{LANGUAGE_VERSION}]::{root_identifier}::{prim.GetPath()}::"
            f"{field_name}::{digest}::{target_device}"
        )

    def resolve(request):
        field_name = request.instance_name
        if field_name not in definitions:
            return None
        if field_name in native_names:
            raise _diagnostic("E_COLLISION", f"a native field named '{field_name}' already exists")

        definition = definitions[field_name]
        if not definition.enabled:
            raise _diagnostic("E_DISABLED_DEPENDENCY", f"derived field '{field_name}' is disabled")
        tree = _parse(definition.expression, definition.language_version)
        dependency_names = sorted(_dependencies(tree))
        if not dependency_names:
            raise _diagnostic(
                "E_NO_DEPENDENCY",
                "a derived field must reference at least one field on the same prim",
                tree.body,
            )
        target_device = _device_alias(request.device)
        compute_device = (
            target_device if definition.compute_device == "auto" else _device_alias(definition.compute_device)
        )
        component_count = _component_count(field_name, definitions, native_counts)
        persistent_cache_key = expression_cache_key(field_name, target_device)
        if component_count == 1:
            cached = cache.get(persistent_cache_key, timeCode=time_code)
            if cached is not None:
                return cached

        dependencies = {
            dependency: request.resolve(dependency, device=compute_device) for dependency in dependency_names
        }
        sizes = {value.size for value in dependencies.values()}
        devices = {_device_alias(value.device) for value in dependencies.values()}
        if len(sizes) != 1:
            raise ValueError("all expression dependencies must have the same tuple count")
        if len(devices) != 1:
            raise ValueError("all expression dependencies must be on the same device")

        size = sizes.pop()
        device = devices.pop()
        inputs = {
            dependency: _materialize_value(simdata.Field.from_array(value, simdata.AssociationType.NOT_SPECIFIED))
            for dependency, value in dependencies.items()
        }
        output = _evaluate_node(tree.body, inputs, size, device)
        result = (
            simdata.Field.from_arrays(output, simdata.AssociationType.NOT_SPECIFIED).to_array()
            if isinstance(output, list)
            else output
        )
        if _device_alias(result.device) != target_device:
            result = result.to(target_device)
        if component_count == 1:
            cache.put_ex(
                persistent_cache_key,
                result,
                prims=[cache.PrimWatch(prim)],
                timeCode=time_code,
            )
        return result

    return resolve
