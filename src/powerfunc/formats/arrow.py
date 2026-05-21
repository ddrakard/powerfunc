from contextlib import nullcontext

try:
    import pyarrow as pa
    import pyarrow.csv as pa_csv
    import pyarrow.dataset as pa_dataset
    import pyarrow.feather as pa_feather
    import pyarrow.ipc as pa_ipc
    import pyarrow.parquet as pq

    from powerfunc.conversions import as_context, register_converters

    def _write_arrow(table, path):
        with pa_ipc.new_file(path, table.schema) as writer:
            writer.write_table(table)

    register_converters(
        pa.Table,
        ".arrow",
        reader=as_context(lambda p: pa_ipc.open_file(p).read_all()),
        writer=_write_arrow,
    )
    register_converters(
        pa.Table,
        ".csv",
        reader=as_context(pa_csv.read_csv),
        writer=lambda t, p: pa_csv.write_csv(t, p),
    )
    register_converters(
        pa.Table,
        ".feather",
        reader=as_context(pa_feather.read_table),
        writer=lambda t, p: pa_feather.write_feather(t, p),
    )
    register_converters(
        pa.Table,
        ".parquet",
        reader=as_context(pq.read_table),
        writer=lambda t, p: pq.write_table(t, p),
    )

    register_converters(
        pa_dataset.Dataset,
        ".arrow",
        reader=lambda p: nullcontext(pa_dataset.dataset(p, format="ipc")),
    )
    register_converters(
        pa_dataset.Dataset,
        ".csv",
        reader=lambda p: nullcontext(pa_dataset.dataset(p, format="csv")),
    )
    register_converters(
        pa_dataset.Dataset,
        ".feather",
        reader=lambda p: nullcontext(pa_dataset.dataset(p, format="ipc")),
    )
    register_converters(
        pa_dataset.Dataset,
        ".parquet",
        reader=lambda p: nullcontext(pa_dataset.dataset(p, format="parquet")),
    )
except ImportError:
    pass
