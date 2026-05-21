try:
    import polars as pl

    from powerfunc.conversions import as_context, register_converters

    _NATIVE_PROTOCOLS = {"gs", "s3", "az", "https"}

    register_converters(
        pl.DataFrame,
        ".csv",
        reader=as_context(pl.read_csv),
        writer=lambda df, p: df.write_csv(p),
        native_protocols=_NATIVE_PROTOCOLS,
    )
    register_converters(
        pl.DataFrame,
        ".parquet",
        reader=as_context(pl.read_parquet),
        writer=lambda df, p: df.write_parquet(p),
        native_protocols=_NATIVE_PROTOCOLS,
    )
    register_converters(
        pl.DataFrame,
        ".json",
        reader=as_context(pl.read_json),
        writer=lambda df, p: df.write_json(p),
    )
    try:
        import openpyxl  # noqa: F401

        register_converters(
            pl.DataFrame,
            ".xlsx",
            reader=as_context(pl.read_excel),
            writer=lambda df, p: df.write_excel(p),
            native_protocols={"https"},
        )
    except ImportError:
        pass
except ImportError:
    pass
