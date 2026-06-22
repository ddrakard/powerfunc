from functions import make


rule make:
    output: "out.csv"
    params: n=4
    run:
        make.snakemake()
