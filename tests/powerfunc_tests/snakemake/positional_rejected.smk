from functions import scale


rule scale:
    input: "data.csv"
    output: "out.csv"
    params: factor=3
    run:
        scale.snakemake()
