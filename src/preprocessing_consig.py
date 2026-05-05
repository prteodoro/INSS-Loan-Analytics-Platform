import polars as pl
from datetime import datetime

def fix_dates(lf, date_columns):
    today = datetime.today().date()

    for col in date_columns:
        parsed = pl.col(col).str.strptime(pl.Date, '%m-%d-%y', strict=False)
        lf = lf.with_columns(
            pl.when(parsed > today)
            .then(parsed.dt.offset_by('-100y'))
            .otherwise(parsed)
            .alias(col)
        )
    return lf

def fix_bancoemprestimo(lf):
    lf = lf.with_columns(
        pl.col('bancoemprestimo')
        .str.replace(r'\.0$', '') # drop .0
        .cast(pl.Int64, strict=False)
    )
    return lf


def fix_esp_and_mr(lf):
    return (
        lf.with_columns([
            pl.col('mr').cast(pl.Float64, strict=False),
            pl.col('esp').cast(pl.Int64, strict=False)
        ])
    )


# def add_aggregations(lf):
#     required_columns = ['nb', 'cpf', 'bancoemprestimo', 'vlemprestimo']
#     schema_cols = lf.collect_schema().names()
#     for col in required_columns:
#         if col not in schema_cols:
#             raise ValueError(f'Missing required column: {col}')

#     lf = lf.with_columns([
#         pl.col('nb').n_unique().over('cpf').alias('nb_unique'),
#         pl.len().over('nb').alias('qtd_contratos'),
#         pl.len().over('cpf').alias('allNB_qtd_contratos'),
#         pl.len().over(['bancoemprestimo', 'nb']).alias('qtd_same_bank_contratos'),
#         pl.col('vlemprestimo').sum().over(['bancoemprestimo', 'cpf']).alias('sum_same_bank_filter'),
#         pl.col('vlemprestimo').sum().over(['cpf']).alias('sum_vlemprestimo'),
#     ])
#     return lf
