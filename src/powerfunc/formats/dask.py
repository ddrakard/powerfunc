try:
    import dask.dataframe as dd

    from powerfunc.conversions import as_context, register_converters

    _NATIVE_PROTOCOLS = {"gs", "s3", "az", "https"}

    register_converters(
        dd.DataFrame, ".csv", reader=as_context(dd.read_csv), native_protocols=_NATIVE_PROTOCOLS
    )
    register_converters(
        dd.DataFrame,
        ".parquet",
        reader=as_context(dd.read_parquet),
        native_protocols=_NATIVE_PROTOCOLS,
    )
except ImportError:
    pass
