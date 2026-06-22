from functions import double


rule double:
    input: "data.csv"
    output: "out.csv"
    run:
        double.snakemake()
