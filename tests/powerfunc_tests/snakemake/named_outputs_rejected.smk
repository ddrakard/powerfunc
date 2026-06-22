from functions import split


rule split:
    input: "data.csv"
    output:
        head="head.csv",
        tail="tail.csv"
    run:
        split.snakemake()
