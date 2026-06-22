from functions import double


rule double:
    input: "data.csv"
    output: "a.csv", "b.csv"
    run:
        double.snakemake()
