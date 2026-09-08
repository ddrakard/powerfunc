import functools
import inspect
import pathlib
import sys
from collections.abc import Callable
from contextlib import ExitStack
from typing import Any, Optional, Protocol, TypeVar, Union, overload

from cloudpathlib import CloudPath
from jsonargparse import ArgumentParser

import powerfunc.command_line as command_line
from powerfunc.command_line import ExpectedException
from powerfunc.compute import ComputeSpecification
from powerfunc.configuration import configuration_paths
from powerfunc.conversions import is_readable, read, write

_EXTRA_PARAMETERS = [
    inspect.Parameter(
        "compute",
        inspect.Parameter.KEYWORD_ONLY,
        default=None,
        annotation=Optional[ComputeSpecification],
    ),
    inspect.Parameter(
        "output_path",
        inspect.Parameter.KEYWORD_ONLY,
        default=None,
        annotation=Optional[str],
    ),
]
# The same option as the command line's ``--config``: a configuration file to
# merge the arguments with, or True for the default files, which the command
# line reads unless told another. A Python call reads none unless asked.
_CONFIGURATION_PARAMETER = inspect.Parameter(
    "config",
    inspect.Parameter.KEYWORD_ONLY,
    default=None,
    annotation=Union[str, pathlib.Path, bool, None],
)


def _configuration_files(config) -> list[str]:
    if config is None or config is False:
        return []
    if config is True:
        return configuration_paths
    return [str(config)]


R = TypeVar("R", covariant=True)


class PowerFunc(Protocol[R]):
    """What :func:`powerfunc` makes of a function.

    Called as the function was, plus ``compute`` to run it elsewhere and
    ``output_path`` to write what it returns to a file; the function's own
    parameters are read from its signature at run time, so they are not checked
    statically here.
    """

    def __call__(
        self,
        *args: Any,
        compute: Optional[ComputeSpecification] = None,
        output_path: Optional[str] = None,
        config: Union[str, pathlib.Path, bool, None] = None,
        **kwargs: Any,
    ) -> R: ...

    def snakemake(self) -> Any:
        """Run this function bound to the surrounding Snakemake rule."""
        ...

    def _run_without_parsing(self, **arguments: Any) -> R:
        """Run with arguments already parsed: by the command line, or before dispatch to compute."""
        ...


def optional_arguments_decorator(decorator):
    """Allows a decorator to be applied with or without argument parentheses."""

    @functools.wraps(decorator)
    def wrapper(function=None, **kwargs):
        if function is not None:
            return decorator(function, **kwargs)
        return functools.partial(decorator, **kwargs)

    return wrapper


@overload
def powerfunc(function: Callable[..., R], *, cli: bool = True) -> PowerFunc[R]: ...
@overload
def powerfunc(
    function: None = None, *, cli: bool = True
) -> Callable[[Callable[..., R]], PowerFunc[R]]: ...
@optional_arguments_decorator
def powerfunc(function=None, *, cli=True):
    """Decorator to turn a function into a powerfunc function.

    Applied bare, ``@powerfunc``, or with arguments, ``@powerfunc(cli=False)``.
    """
    # eval_str=True required for `from __future__ import annotations`
    signature = inspect.signature(function, eval_str=True)
    reserved = {param.name for param in [*_EXTRA_PARAMETERS, _CONFIGURATION_PARAMETER]}
    taken = reserved & signature.parameters.keys()
    if taken:
        raise TypeError(
            f"{function.__name__} has parameters powerfunc adds itself: {', '.join(sorted(taken))}."
        )
    modified_signature = signature.replace(
        parameters=[
            param.replace(
                # str must precede pathlib.Path and CloudPath: jsonargparse resolves Union
                # subtypes in order and pathlib.Path accepts any string without error, so it
                # would win and mangle "gs://bucket/file" into PosixPath("gs:/bucket/file").
                annotation=Union[param.annotation, str, pathlib.Path, CloudPath]
                if is_readable(param.annotation)
                else param.annotation
            )
            for param in signature.parameters.values()
        ]
        + _EXTRA_PARAMETERS
    )

    # Two entry points: wrapper takes a Python call's arguments as they are,
    # filling in from a configuration file if one is named, then
    # _run_without_parsing dispatches to compute if asked, else reads the path
    # arguments, calls the function and writes the result. The command line,
    # having parsed argv and the default configuration files with jsonargparse,
    # and the compute provider, given arguments without ``compute``, both enter
    # at _run_without_parsing.
    calling_signature = modified_signature.replace(
        parameters=[*modified_signature.parameters.values(), _CONFIGURATION_PARAMETER]
    )

    def _from_configuration(files, given):
        """The arguments the configuration ``files`` hold, other than those ``given``."""

        def dummy():
            pass

        dummy.__signature__ = modified_signature
        parser = ArgumentParser(exit_on_error=False, default_config_files=files)
        parser.add_function_arguments(dummy)
        try:
            return {
                name: value
                for name, value in vars(parser.instantiate(parser.get_defaults())).items()
                if name not in given
            }
        except Exception as e:
            raise ExpectedException(str(e)) from e

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        """Run with the arguments as given, and ``config``'s for the rest."""
        arguments = dict(calling_signature.bind_partial(*args, **kwargs).arguments)
        files = _configuration_files(arguments.pop(_CONFIGURATION_PARAMETER.name, None))
        if files:
            arguments.update(_from_configuration(files, arguments))
        try:
            bound = modified_signature.bind(**arguments)
        except TypeError as e:
            raise ExpectedException(str(e)) from e
        bound.apply_defaults()
        return _run_without_parsing(**bound.arguments)

    def _run_without_parsing(**arguments):
        """Run on the compute asked for, or here: read the files given, write the result."""
        compute = arguments.pop("compute", None)
        if compute is not None:
            return compute.provider.call(wrapper, arguments, compute)
        output_path = arguments.pop("output_path", None)
        with ExitStack() as stack:
            kwargs = {
                name: stack.enter_context(read(arguments[name], param.annotation))
                for name, param in signature.parameters.items()
            }
            result = function(**kwargs)
        if output_path is not None:
            write(result, output_path)
            return output_path
        return result

    wrapper.__signature__ = calling_signature
    # The CLI parses by this entry's signature and describes it by its docstring
    # (else by its repr, which would name this entry, not the function).
    _run_without_parsing.__doc__ = function.__doc__ or function.__name__
    _run_without_parsing.__signature__ = modified_signature
    wrapper._run_without_parsing = _run_without_parsing

    def snakemake():
        """Run this function bound to the surrounding Snakemake rule."""
        from powerfunc.integrations import snakemake as snakemake_integration

        frame = sys._getframe(1)
        return snakemake_integration.run(wrapper, frame)

    wrapper.snakemake = snakemake

    if cli and function.__module__ == "__main__":
        command_line.cli_functions[function.__name__] = _run_without_parsing

    return wrapper
