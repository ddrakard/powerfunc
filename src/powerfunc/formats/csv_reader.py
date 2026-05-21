import csv
from contextlib import contextmanager

from powerfunc.conversions import register_converters


@contextmanager
def _read_csv(path):
    with open(path, newline="") as file:
        yield csv.reader(file)


register_converters(csv.reader, ".csv", reader=_read_csv)
