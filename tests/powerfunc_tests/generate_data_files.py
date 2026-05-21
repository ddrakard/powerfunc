import pathlib

import pandas as pd
import pyarrow.feather as pa_feather
import pyarrow.ipc as pa_ipc

DATA_DIR = pathlib.Path(__file__).parent / "data"

DATA = pd.DataFrame({"value": [1, 2, 3]})


def generate():
    DATA_DIR.mkdir(exist_ok=True)

    DATA.to_csv(DATA_DIR / "data.csv", index=False)

    DATA.to_parquet(DATA_DIR / "data.parquet")
    DATA.to_json(DATA_DIR / "data.pandas.json")
    DATA.to_excel(DATA_DIR / "data.xlsx", index=False)

    import pyarrow as pa

    arrow_table = pa.Table.from_pandas(DATA)
    pa_feather.write_feather(arrow_table, DATA_DIR / "data.feather")
    with pa_ipc.new_file(DATA_DIR / "data.arrow", arrow_table.schema) as writer:
        writer.write_table(arrow_table)

    import polars as pl

    pl.from_pandas(DATA).write_json(DATA_DIR / "data.polars.json")


if __name__ == "__main__":
    generate()
