"""Run a powerfunc function inside a Snakemake rule.

Call ``my_function.snakemake()`` inside a Snakemake ``run:`` block and the
rule's inputs, params and outputs are bound to the function automatically.

.. code-block:: python

    # Snakefile
    from my_module import my_function

    rule example:
        input: "data.csv"
        output: "result.csv"
        run:
            my_function.snakemake()

Binding rules:
    - Inputs and params become the function's arguments. When both are
      present they must all be named (keyword); positional entries are only
      allowed when one of the two is absent.
    - A single unnamed output receives the function's return value, written
      through powerfunc's normal converters.
    - Named outputs and multiple outputs are not supported.
"""

import types
from typing import Any, Callable

from snakemake.iocontainers import (
    InputFiles,
    Log,
    Namedlist,
    OutputFiles,
    Params,
    ResourceList,
    Snakemake,
    Wildcards,
)

from powerfunc.command_line import ExpectedException


def _split_namedlist(namedlist: Namedlist) -> tuple[list[Any], dict[str, Any]]:
    """Split a Snakemake ``Namedlist`` into (positional_values, {name: value})."""
    named = dict(namedlist.items()) if hasattr(namedlist, "items") else {}
    names_map = getattr(namedlist, "_names", {}) or {}
    named_indices = set()
    for start, end in names_map.values():
        if end is None:
            named_indices.add(start)
        else:
            named_indices.update(range(start, end))
    all_values = list(namedlist)
    positional = [value for index, value in enumerate(all_values) if index not in named_indices]
    return positional, named


def _unpack_path_or_paths(value: str | Namedlist) -> str | list[str]:
    """Normalise a Snakemake input/output entry to a path string (or list of them)."""
    if isinstance(value, (list, tuple, Namedlist)):
        return [str(item) for item in value]
    return str(value)


def _get_context(caller_frame: types.FrameType) -> Snakemake:
    """Build a :class:`Snakemake` context from the caller's ``run:`` block locals."""
    ns = {**caller_frame.f_globals, **caller_frame.f_locals}

    inp = ns.get("input")
    if not isinstance(inp, InputFiles):
        raise RuntimeError(".snakemake() was called outside of a Snakemake run: block.")

    return Snakemake(
        input_=inp,
        output=ns.get("output", OutputFiles()),
        params=ns.get("params", Params()),
        wildcards=ns.get("wildcards", Wildcards()),
        threads=ns.get("threads", 1),
        resources=ns.get("resources", ResourceList()),
        log=ns.get("log", Log()),
        config=ns.get("config", {}),
        rulename=ns.get("rule", ""),
        bench_iteration=None,
    )


def run(function: Callable, caller_frame: types.FrameType) -> Any:
    """Bind the current Snakemake rule to ``function`` and call it."""
    ctx = _get_context(caller_frame)

    input_positional, input_named = _split_namedlist(ctx.input)
    params_positional, params_named = _split_namedlist(ctx.params)
    output_positional, output_named = _split_namedlist(ctx.output)

    inputs_present = bool(input_positional or input_named)
    params_present = bool(params_positional or params_named)
    if inputs_present and params_present and (input_positional or params_positional):
        raise ExpectedException(
            "When both inputs and params are given they must all be named. "
            "Positional inputs or params are only allowed when one of the two is absent."
        )

    args = [_unpack_path_or_paths(value) for value in input_positional] + list(params_positional)
    kwargs = {name: _unpack_path_or_paths(value) for name, value in input_named.items()}
    kwargs.update(params_named)

    if output_named:
        raise ExpectedException(
            "Named outputs are not supported. Use a single unnamed output path."
        )
    if len(output_positional) > 1:
        raise ExpectedException(
            "Multiple outputs are not supported. Use a single unnamed output path."
        )

    if output_positional:
        return function(*args, output_path=_unpack_path_or_paths(output_positional[0]), **kwargs)
    return function(*args, **kwargs)
