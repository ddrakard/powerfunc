from functions import scale


rule scale:
    input:
        df="data.csv"
    output: "out.csv"
    params:
        factor=3
    run:
        scale.snakemake()
