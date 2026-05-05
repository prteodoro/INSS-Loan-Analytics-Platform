import streamlit as st
import polars as pl
import glob
import os
from preprocessing_consig import fix_dates, fix_bancoemprestimo, fix_esp_and_mr
from datetime import datetime, date

st.title("INSS - Clients Data Explorer")

# ==========================
# Config: safety limits
# ==========================
MAX_ROWS = 160_000 # absolute safeguard for memory
PREVIEW_ROWS = 500 # UI preview rows only


input_folder = '../sample_data'
needed_cols = [
    'nb', 'cpf', 'nome', 'dtnascimento', 'esp', 'mr', 'bancopagto', 'meiopagto',
    'ddb', 'bancoemprestimo', 'contrato', 'vlemprestimo', 'prazo', 'vlparcela',
    'dataaverbacao', 'competencia', 'taxa', 'municipio', 'uf', 'telcel_1',
    'telcel_2', 'telcel_3'
]

# ==========================
# Helper: elapsed months
# ==========================
def add_elapsed_months(lf, col='competencia'):
    current = datetime.now().year * 12 + datetime.now().month
    return lf.with_columns(
        (
            pl.lit(current, dtype=pl.Int64) 
            - ((pl.col(col).cast(pl.Int64) // 100) * 12 
            + (pl.col(col).cast(pl.Int64) % 100))
        ).alias('pagas')
    )

# ==========================
# Helper: Calculate remaining months
# ==========================
def add_remaining_months(lf, competencia_col='competencia', prazo_col='prazo'):
    current = datetime.now().year * 12 + datetime.now().month
    start_month = (pl.col(competencia_col).cast(pl.Int64) // 100) * 12 + (
        pl.col(competencia_col).cast(pl.Int64) % 100
    )
    end_month = start_month + pl.col(prazo_col).cast(pl.Int64)
    return lf.with_columns(
        (
            end_month - pl.lit(current, dtype=pl.Int64)
        ).alias('remain_months')
    )

# ==========================
# Helper: Calculate outstanding balance, valor liberado, total liberado
# ==========================
def add_calculate_values(lf):
    if 'remain_months' not in lf.collect_schema().names():
        lf = add_remaining_months(lf)

        # -------------------
        # outstanding balance
        # -------------------
    # Convert taxa % -> decimal and compute outstanding balance
    lf = lf.with_columns(
        (
            (
                ((1 - (1 + (pl.col('taxa') / 100)) ** - pl.col('remain_months'))
                / (pl.col('taxa') / 100))
                * pl.col('vlparcela')
            ).round(2)
            .alias('saldo_devedor')
        )
    )

    # -------------------
    # Valor liberado
    # -------------------

    # Factors
    factor_1 = 0.02377
    factor_2 = 0.02221

    # Add valor liberado 1 and 2
    lf = lf.with_columns([
        ((pl.col('vlparcela') / factor_1) - pl.col('saldo_devedor'))
        .round(2)
        .alias('vl_liberado_1'),
        ((pl.col('vlparcela') / factor_2) - pl.col('saldo_devedor'))
        .round(2)
        .alias('vl_liberado_2')
    ])

    return lf
    
# ==========================
# Precompute totals from full dataset
# ==========================
# Collect only aggregated tables (much smaller)
@st.cache_data
def compute_full_aggregations(input_folder, needed_cols):
    total_loans_full_list = []
    total_same_bank_per_cpf_list = []
    total_salary_per_cpf_list = []

    for uf_file in sorted(os.listdir(input_folder)):
        if not uf_file.endswith('.parquet'):
            continue
        file_path = os.path.join(input_folder, uf_file)
        lf_uf = pl.scan_parquet(file_path).select(needed_cols)

        # Preprocessing
        lf_uf = fix_dates(lf_uf, ['dtnascimento', 'dataaverbacao'])
        lf_uf = fix_bancoemprestimo(lf_uf)
        lf_uf = fix_esp_and_mr(lf_uf)
        lf_uf = add_elapsed_months(lf_uf)
        lf_uf = add_remaining_months(lf_uf)
        lf_uf = add_calculate_values(lf_uf)

        # Aggregations per UF

        total_loans_full_list.append(
            lf_uf.group_by('cpf')
            .agg(pl.col('vlemprestimo').sum().alias('sum_vlemprestimo_full'))
        )
        total_same_bank_per_cpf_list.append(
            lf_uf.group_by(['cpf', 'bancoemprestimo'])
            .agg(pl.col('vlemprestimo').sum().alias('sum_same_bank_full'))
        )
        total_salary_per_cpf_list.append(
            lf_uf.group_by(['cpf', 'nb'])
            .agg(pl.col('mr').first()) # one salary per matricula
            .group_by('cpf')
            .agg(pl.col('mr').sum().alias('total_mr')) # sum across matriculas
        )

    # Combine all UFS
    total_loans_full = pl.concat(total_loans_full_list)
    total_same_bank_per_cpf = pl.concat(total_same_bank_per_cpf_list)
    total_salary_per_cpf = pl.concat(total_salary_per_cpf_list)

    return (
        total_loans_full.lazy(),
        total_same_bank_per_cpf.lazy(),
        total_salary_per_cpf.lazy()
    )

total_loans_full, total_same_bank_per_cpf, total_salary_per_cpf = compute_full_aggregations(input_folder, needed_cols)

# ==========================
# Streamlit Filters Inputs
# ==========================
uf_options = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA",
    "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN",
    "RS", "RO", "RR", "SC", "SP", "SE", "TO"
]
default_uf_options = [
    "AC", "AL", "AM", "BA", "CE", "DF", "ES", "GO", "MA",
    "MT", "MS", "MG", "PA", "PR", "PE", "PI", "RJ", "RN",
    "RS", "RO", "SC", "SP", "SE"
]
selected_uf = st.multiselect(
    "Filter by UF", 
    options=uf_options,
    default=default_uf_options
    )

# Bank filter
banco_options = [
    1, 3, 4, 12, 21, 29, 33, 41, 47, 69, 70, 79, 81, 104, 121, 174, 189, 213,
    237, 254, 276, 318, 329, 330, 335, 341, 359, 368, 373, 386, 389, 394, 402,
    422, 465, 470, 604, 611, 623, 626, 643, 655, 707, 748, 752, 753, 756, 901,
    902, 903, 905, 908, 917, 921, 925, 926, 932, 934, 935, 936, 954, 957, 961,
    964, 965, 968, 971, 973, 999
]
default_bank_options = [
    29, 
    41,
    #121, 
    174,
    254, 
    318, 
    335, 
    394, 
    402, 
    422, 
    611, 
    623,
    655, 
    #707,
    908,
    935,
    954
]
selected_banco = st.multiselect(
    "Filter by Lending Bank", 
    options=banco_options,
    default=default_bank_options
    )

# Default minimum for all banks
DEFAULT_MIN_MONTHS = 13

# Create a dictionary with default minimum months for some banks
bank_min_months_default = {
    29: 26,
    623: 38,  
}

# Apply defaults automatically
bank_min_months = {
    banco: bank_min_months_default.get(banco, DEFAULT_MIN_MONTHS)
    for banco in selected_banco
}

esp_beneficio = [
    1, 2, 3, 4, 5, 6, 7, 8, 11, 12, 18, 19, 20, 21, 22, 23,
    24, 26, 27, 28, 29, 30, 32, 33, 34, 37, 38, 40, 41, 42,
    43, 44, 45, 46, 49, 51, 52, 54, 55, 56, 57, 58, 59, 60,
    72, 78, 81, 82, 83, 84, 87, 88, 89, 92, 93, 96
]

default_esp_beneficio = [
    1, 2, 3, 4, 5, 6, 7, 8, 11, 12, 18, 19, 20, 21, 22, 23,
    24, 26, 27, 28, 29, 30, 32, 33, 34, 37, 38, 40, 41, 42,
    43, 44, 45, 46, 49, 51, 52, 54, 55, 56, 57, 58, 59, 60,
    72, 78, 81, 82, 83, 84, 89, 92, 93, 96
]
selected_esp = st.multiselect(
    "Filter by ESP",
    options=esp_beneficio,
    default=default_esp_beneficio
    )

# Date of Birth filter
min_date = date(1952, 1, 1)
max_date = date.today()
default_start_date = date(1966, 12, 31)
start_date, end_date = st.date_input(
    "Date of Birth Range",
    value=[min_date, default_start_date],
    min_value=min_date,
    max_value=max_date
)

# CPF filter
cpf_search = st.text_input("Search by CPF")

# Minimum wage
min_wage = st.number_input('Minimum total wage', min_value=0, value=1500)
# Maximum wage
max_wage = st.number_input('Maximum total wage', value=8000)

# Minimum paid installments
#min_months_paid = st.number_input("Minimum paid installments", min_value=0, value=24)
# Mininum months remaining
min_months_remaining = st.number_input('Minimum months remaining', min_value=0, value=47)

# Interest rate
min_taxa = st.number_input("Minimum Interest Rate (%)", value=1.65, step=0.01)
max_taxa = st.number_input("Maximum Interest Rate (%)", value=1.8, step=0.01)

# Minimum loan per contract 
min_loan_per_contract = st.number_input(
    'Minimum loan per contract', min_value=0.0, value=1500.0, step=100.0
)

# Minimum total loan filters
min_total_loan_filtered = st.number_input(
    "Minimum total loan per client (after filters)", min_value=0.0, value=4000.0, step=100.0
    )
# Maximum total loan filters
max_total_loan_filtered = st.number_input(
    'Maximum total loan per client (after filters)', value=550000.0, step=100.0
)

# Minimum total liberado
min_total_lib = st.number_input(
    'Minimum total liberado', step=100.0
)

# Unique bank
unique_bank = st.number_input(
    'Unique bank greater or equal', min_value=1, max_value=15, value=1, step=1
)

# ==========================
# Button: Run heavy filters + joins
# ==========================
if st.button('Run Search'):
    start_time = datetime.now()
    print(f'Start time: {datetime.now().strftime("%Y/%m/%d_%H:%M:%S")}')
    st.write(f'Start time: {datetime.now().strftime("%Y/%m/%d_%H:%M:%S")}')

    ufs_filtered_results = []

    # Prepare list of UF files
    uf_files = [f for f in sorted(os.listdir(input_folder)) if f.endswith('.parquet')]
    total_files = len(uf_files)

    # Scan all UF files one by one
    for idx, uf_file in enumerate(uf_files, start=1):
        file_path = os.path.join(input_folder, uf_file)
        #status_text.text(f'Processing {uf_file} ({idx}/{total_files})...')

        # Lazy scan only needed columns
        lf_uf = pl.scan_parquet(file_path).select(needed_cols)
        #lf_uf = pl.scan_parquet(file_path, schema=schema, extra_columns="ignore").select(needed_cols)


        # Preprocessing
        lf_uf = fix_dates(lf_uf, ['dtnascimento', 'dataaverbacao'])
        lf_uf = fix_bancoemprestimo(lf_uf)
        lf_uf = fix_esp_and_mr(lf_uf)

        # Helper columns
        lf_uf = add_elapsed_months(lf_uf)
        lf_uf = add_remaining_months(lf_uf)
        lf_uf = add_calculate_values(lf_uf)

        # ==========================
        # Apply filters lazily
        # ==========================
        today = date.today()

        lf_uf_filtered = (
            lf_uf
            .filter(pl.col('telcel_1') != '')
            .filter(pl.col('uf').is_in(selected_uf))
            .filter(pl.col('bancoemprestimo').is_in(selected_banco))
            .filter(pl.col('esp').is_in(selected_esp))
            .filter((pl.col('dtnascimento') >= pl.lit(start_date)) & 
                    (pl.col('dtnascimento') <= pl.lit(end_date)))
            # Drop clients with esp 32 or 92 if age < 61
            .filter(
                ~(
                    pl.col('esp').is_in([32, 92]) &
                    (
                        (
                            (pl.lit(today.year) - pl.col('dtnascimento').dt.year())
                            - (
                                (pl.col('dtnascimento').dt.month() > pl.lit(today.month))
                                | (
                                    (pl.col('dtnascimento').dt.month() == pl.lit(today.month))
                                    & (pl.col('dtnascimento').dt.day() > pl.lit(today.day))
                                )
                            ).cast(pl.Int32)
                        ) < 60
                    )
                )
            )
            # Dynamic filter per bank
            .filter(
                pl.any_horizontal([
                    (pl.col('bancoemprestimo') == banco) & (pl.col('pagas') >= min_pagas)
                    for banco, min_pagas in bank_min_months.items()
                ])
            )
            .filter(pl.col('remain_months') >= min_months_remaining)
            .filter((pl.col('taxa') >= min_taxa) & (pl.col('taxa') <= max_taxa))
            .filter(pl.col('vlemprestimo') >= min_loan_per_contract)
        )

        if cpf_search:
            lf_uf_filtered = lf_uf_filtered.filter(pl.col('cpf').str.contains(cpf_search))

        # ==========================
        # Limit rows for preview (cap BEFORE any heavy aggregations)
        # ==========================
        #lf_small = lf_filtered.limit(MAX_ROWS)
        # lf_uf_small = lf_uf_filtered

        # ==========================
        # Aggregations that respect filters (built on lf_small; remain lazy)
        # ==========================
        agg_cpf_filtered = (
            lf_uf_filtered.group_by('cpf')
            .agg([
                # Total unique NB per CPF
                pl.col('nb').n_unique().alias('qtd_nb'),
                # Total unique bancoemprestimo per CPF
                pl.col('bancoemprestimo').n_unique().alias('unique_bank'),
                # Total vlemprestimo per cpf with the filters
                pl.col('vlemprestimo').sum().alias('sum_vlemprestimo'),
                pl.sum('vl_liberado_1').alias('total_1'),
                pl.sum('vl_liberado_2').alias('total_2')
            ])
        )

        agg_cpf_bank_filtered = (
            lf_uf_filtered.group_by(['cpf', 'bancoemprestimo'])
            .agg([
                # Total same bancoemprestimo per CPF
                pl.count('bancoemprestimo').alias('qtd_same_bank'),
                # Total vlemprestimo per bancoemprestimo per CPF
                pl.col('vlemprestimo').sum().alias('sum_same_bank_filter')
            ])
        )

        # Count unique CPFs per NB
        cpf_count_per_nb = lf_uf_filtered.group_by(['nb', 'cpf']).agg(
            pl.count('cpf').alias('qtd_contratos_nb')
        )

        # ==========================
        # Safe limited join
        # ==========================
        lf_uf_result = (
            lf_uf_filtered
            # filtered metrics
            .join(cpf_count_per_nb, on=['nb', 'cpf'], how='left')
            .join(agg_cpf_filtered, on='cpf', how='left')
            .join(agg_cpf_bank_filtered, on=['cpf', 'bancoemprestimo'], how='left')
            # always from full dataset
            .join(total_same_bank_per_cpf, on=['cpf', 'bancoemprestimo'], how='left')
            .join(total_loans_full, on='cpf', how='left')
            .join(total_salary_per_cpf, on='cpf', how='left')
            # Filter by total loan after filter
            .filter((pl.col('sum_vlemprestimo') >= min_total_loan_filtered) &
                (pl.col('sum_vlemprestimo') <= max_total_loan_filtered))
            .filter((pl.col('total_mr') >= min_wage) & (pl.col('total_mr') <= max_wage))
            .filter(pl.col('unique_bank') >= unique_bank)
            .filter(pl.col('total_2') >= min_total_lib)
            )

        # enforce column order
        extras = [ 'saldo_devedor', 'vl_liberado_1', 'vl_liberado_2', 'total_1', 'total_2']

        # Current columns produced by the lazyframe (preserves order)
        current_cols = lf_uf_result.collect_schema().names()

        # Keep only extras that actually exist in the frame (avoid KeyError)
        existing_extras = [c for c in extras if c in current_cols]

        # Build final order: all current cols except any of the extras (to avoid duplicates),
        # then append the extras that exist.abs
        final_cols = [c for c in current_cols if c not in existing_extras] + existing_extras

        # Reorder (select will keep only columns that really exist; safe)
        lf_uf_result = lf_uf_result.select(final_cols)

        # Append UF result to list
        ufs_filtered_results.append(lf_uf_result)

    # ========================
    # Combine all UFs into one Lazyframe
    # ========================
    if ufs_filtered_results:
        lf_filtered_full = pl.concat(ufs_filtered_results)
    else:
        lf_filtered_full = pl.DataFrame([]).lazy() # empty fallback

    print(f'Finished all joins and aggregations: '
        f'{datetime.now().strftime("%Y/%m/%d_%H:%M:%S")}')
    st.write(
        f'Finished all joins and aggregations: '
        f'{datetime.now().strftime("%Y/%m/%d_%H:%M:%S")}')

    # ==========================
    # Limit rows to safeguard memory
    # ==========================
    stats = (
        lf_filtered_full.select([
            pl.len().alias('row_count'),
            pl.col('cpf').n_unique().alias('unique_cpfs')
        ])
        .collect(engine='streaming') # single execution
    )

    row_count = stats['row_count'][0]
    unique_cpfs = stats['unique_cpfs'][0]

    print(f"Rows: {row_count}, Unique CPFs: {unique_cpfs}")
    st.write(f"Rows: {row_count}, Unique CPFs: {unique_cpfs}")
    print(f'Finished row_count: {datetime.now().strftime("%Y/%m/%d_%H:%M:%S")}')
    st.write(f'Finished row_count: {datetime.now().strftime("%Y/%m/%d_%H:%M:%S")}')

    if row_count > MAX_ROWS:
        st.warning(
            f'Too many rows after filtering: {row_count:,}.'
            f'Please narrow down filters.'
        )
        st.stop()

    # Save lazyframe into session_state
    st.session_state['lf_filtered_full'] = lf_filtered_full
    st.success('Search completed ✅ - now you can Collect and Preview')

# ==============================
# Collect and Preview button
# ==============================
if 'lf_filtered_full' in st.session_state:
    if st.button('Collect and Preview Data'):
        with st.spinner('Collecting data... this may take a while'):
            #lf_preview_full = lf_preview_full.collect(engine='streaming')
            lf_filtered_full = st.session_state['lf_filtered_full'].collect(engine='streaming')

        st.success(f'Finished collect ✅: {datetime.now().strftime("%Y/%m/%d_%H:%M:%S")}')
        print(f'Finished collect: {datetime.now().strftime("%Y/%m/%d_%H:%M:%S")}')

        # ==========================
        # Collect only the first N rows for preview
        # ==========================
        result_preview = lf_filtered_full.head(PREVIEW_ROWS)

        st.subheader('Filtered Data Preview')
        st.dataframe(result_preview)

        st.markdown(f'Total rows after filtering: {lf_filtered_full.shape[0]}')
        # Unique CPFs after filtering
        unique_cpf_after_filter = int(lf_filtered_full['cpf'].n_unique())
        st.markdown(
            f"**Number of unique CPFs after filtering:** {unique_cpf_after_filter}"
            )

        # ==========================
        # Download filtered data
        # ==========================
        csv_text = lf_filtered_full.write_csv()
        date_download = datetime.now().strftime("%Y%m%d_%Hh%Mm")
        file_name = f"{unique_cpf_after_filter}_filtered_clients_{date_download}.csv"
        st.download_button(
            "Download Filtered Data as CSV",
            csv_text,
            file_name,
            mime="text/csv"
            )

        # === Prepare and export the smaller SMS CSV ===
        sms_selected_columns = [
            'nome', 'cpf', 'total_1', 'total_2',
            'telcel_1', 'telcel_2', 'telcel_3'
        ]

        df_sms = lf_filtered_full.select(sms_selected_columns)

        sms_file_name = f'for_sms_{file_name}'
        sms_csv_text = df_sms.write_csv()

        st.download_button(
            'Download SMS CSV',
            sms_csv_text,
            sms_file_name,
            mime='text/csv'
        )
    else:
        st.info('Click **Collect and Preview Data** to load the filtered dataset.')
