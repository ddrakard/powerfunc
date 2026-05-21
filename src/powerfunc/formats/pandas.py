try:
    import pandas as pd

    from powerfunc.conversions import as_context, register_converters

    _NATIVE_PROTOCOLS = {"gs", "s3", "az", "https"}

    register_converters(
        pd.DataFrame,
        ".arrow",
        reader=as_context(pd.read_feather),
        writer=lambda df, p: df.to_feather(p),
    )
    register_converters(
        pd.DataFrame,
        ".csv",
        reader=as_context(pd.read_csv),
        writer=lambda df, p: df.to_csv(p, index=False),
        native_protocols=_NATIVE_PROTOCOLS,
    )
    register_converters(
        pd.DataFrame,
        ".parquet",
        reader=as_context(pd.read_parquet),
        writer=lambda df, p: df.to_parquet(p),
        native_protocols=_NATIVE_PROTOCOLS,
    )
    register_converters(
        pd.DataFrame,
        ".feather",
        reader=as_context(pd.read_feather),
        writer=lambda df, p: df.to_feather(p),
    )
    register_converters(
        pd.DataFrame,
        ".json",
        reader=as_context(pd.read_json),
        writer=lambda df, p: df.to_json(p),
        native_protocols=_NATIVE_PROTOCOLS,
    )
    try:
        import openpyxl  # noqa: F401

        register_converters(
            pd.DataFrame,
            ".xlsx",
            reader=as_context(pd.read_excel),
            writer=lambda df, p: df.to_excel(p, index=False),
            native_protocols=_NATIVE_PROTOCOLS,
        )
    except ImportError:
        pass
    try:
        import xlrd  # noqa: F401

        register_converters(
            pd.DataFrame,
            ".xls",
            reader=as_context(pd.read_excel),
            native_protocols=_NATIVE_PROTOCOLS,
        )
    except ImportError:
        pass
except ImportError:
    pass
