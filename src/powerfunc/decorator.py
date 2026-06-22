import functools
import inspect
import pathlib
import sys
from contextlib import ExitStack
from typing import Optional, Union

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


def optional_arguments_decorator(decorator):
    """Allows a decorator to be applied with or without argument parentheses."""

    @functools.wraps(decorator)
    def wrapper(function=None, **kwargs):
        if function is not None:
            return decorator(function, **kwargs)
        return functools.partial(decorator, **kwargs)

    return wrapper


@optional_arguments_decorator
def powerfunc(function, *, cli=True):
    """Decorator to turn a function into a powerfunc function."""
    signature = inspect.signature(function)
    # str must precede pathlib.Path and CloudPath: jsonargparse resolves Union subtypes in
    # order and pathlib.Path accepts any string without error, so it would win and mangle
    # "gs://bucket/file" into PosixPath("gs:/bucket/file").
    modified_signature = signature.replace(
        parameters=[
            param.replace(
                annotation=Union[param.annotation, str, pathlib.Path, CloudPath]
                if is_readable(param.annotation)
                else param.annotation
            )
            for param in signature.parameters.values()
        ]
        + _EXTRA_PARAMETERS
    )

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        cli_mode = command_line._cli_active
        if cli_mode:
            command_line._cli_active = False
            resolved_args = dict(kwargs)
        else:
            merged_args = dict(modified_signature.bind_partial(*args, **kwargs).arguments)

            def dummy():
                pass

            dummy.__signature__ = modified_signature
            parser = ArgumentParser(exit_on_error=False, default_config_files=configuration_paths)
            parser.add_function_arguments(dummy)
            try:
                resolved_args = vars(parser.instantiate(parser.parse_object(merged_args)))
            except Exception as e:
                raise ExpectedException(str(e)) from e
        compute = resolved_args.pop("compute", None)

        if compute is not None:
            return compute.provider.call(function, dict(resolved_args), compute)

        output_path = resolved_args.pop("output_path", None)

        with ExitStack() as stack:
            kwargs = {
                name: stack.enter_context(read(resolved_args[name], param.annotation))
                for name, param in signature.parameters.items()
            }
            result = function(**kwargs)

        if output_path is not None:
            write(result, output_path)
            return output_path
        return result

    wrapper.__signature__ = modified_signature

    def snakemake():
        """Run this function bound to the surrounding Snakemake rule."""
        from powerfunc.integrations import snakemake as snakemake_integration

        frame = sys._getframe(1)
        return snakemake_integration.run(wrapper, frame)

    wrapper.snakemake = snakemake

    if cli and function.__module__ == "__main__":
        command_line.cli_functions.append((wrapper, modified_signature))

    return wrapper
