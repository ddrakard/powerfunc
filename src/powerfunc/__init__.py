from powerfunc.command_line import enable_cli
from powerfunc.configuration import configuration_paths
from powerfunc.decorator import powerfunc

powerfunc.enable_cli = enable_cli

__all__ = ["configuration_paths", "enable_cli", "powerfunc"]
