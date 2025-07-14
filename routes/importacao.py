from __future__ import annotations
import os
import re
import sqlite3
import pandas as pd
from flask import Blueprint, flash, redirect, request, url_for, jsonify

bp = Blueprint("importacao", __name__, url_prefix="/import")
import_bp = bp  # type: ignore

def _normalize_col(col_raw):
    """Converte formatos de colunas de horário para 'HH:MM'."""
    if isinstance(col_raw, (float, int)) and not pd.isna(col_raw):
        try:
            minutes = int(round(col_raw * 24 * 60))
            h, m = divmod(minutes, 60)
            return f"{h:02d}:{m:02d}"
        except Exception:
            pass
    col_str = str(col_raw).strip()

    # Verificar se é um timestamp datetime
    if "00:00:00" in col_str and len(col_str) > 8:
        # Extrair apenas a parte do horário
        time_part = col_str.split()[1] if " " in col_str else col_str.split("T")[1] if "T" in col_str else col_str
        if ":" in time_part:
            parts = time_part.split(":")
            if len(parts) >= 2:
                return f"{int(parts[0]):02d}:{int(parts[1]):02d}"

    match = re.fullmatch(r"(\d{1,2}):(\d{2})", col_str)
    if match:
        h, m = match.groups()
        return f"{int(h):02d}:{m}"
    return col_str

def _sort_time_columns(horarios):
    """Ordena horários colocando 00:00 no final."""
    def time_sort_key(horario):
        if re.match(r'\d{2}:\d{2}', str(horario)):
            hour, minute = map(int, horario.split(':'))
            # Se for 00:00, tratar como 24:00 para ordenação
            if hour == 0:
                return (24, minute)
            return (hour, minute)
        return (99, 99)  # Colocar horários inválidos no final

    return sorted(horarios, key=time_sort_key)

def process_excel(filepath: str) -> None:
    ext = os.path.splitext(filepath)[1].lower()

    # Primeiro, descobrir qual aba usar
    xls = pd.ExcelFile(filepath)
    sheet_name = xls.sheet_names[0]  # Usar a primeira aba disponível

    read_kwargs: dict = {"sheet_name": sheet_name, "header": None}
    if ext == ".xlsb":
        read_kwargs["engine"] = "pyxlsb"

    df_raw = pd.read_excel(filepath, **read_kwargs)

    # Baseado na análise, a linha 4 (índice 4) contém os cabeçalhos
    # e os dados começam na linha 5 (índice 5)
    header_idx = 4

    # Define cabeçalho
    header_series = df_raw.iloc[header_idx].copy()

    # Normalizar os horários no cabeçalho
    normalized_headers = []
    for col in header_series:
        normalized_headers.append(_normalize_col(col))

    # Criar DataFrame com os dados a partir da linha 5
    df = df_raw.iloc[header_idx + 1:].copy()
    df.columns = normalized_headers

    # Limpar linhas completamente vazias
    df.dropna(how="all", inplace=True)

    # Filtrar apenas as linhas que têm código de item válido (coluna 0)
    df = df[df.iloc[:, 0].notna() & (df.iloc[:, 0] != "")]

    # Identificar colunas de horário (colunas 12 até 28 baseado na análise)
    # Horários estão nas colunas de índice 12 até aproximadamente 28
    codigo_col = df.columns[0]  # "Item"
    descricao_col = df.columns[1]  # "Descrição"

    # Colunas de horário (índices 12 até 28)
    horario_cols = df.columns[12:29].tolist()

    # Filtrar apenas horários válidos (formato HH:MM)
    horario_cols_validos = []
    for col in horario_cols:
        if re.match(r'\d{2}:\d{2}', str(col)):
            horario_cols_validos.append(col)

    # Ordenar horários corretamente (00:00 no final)
    horario_cols_validos = _sort_time_columns(horario_cols_validos)

    # Preparar dados para salvar no banco
    # Vamos criar uma estrutura onde cada linha representa um item com suas quantidades por horário
    dados_processados = []

    for idx, row in df.iterrows():
        codigo = row[codigo_col]
        descricao = row[descricao_col]

        if pd.isna(codigo) or codigo == "":
            continue

        # Criar um dicionário com o código, descrição e quantidades por horário
        item_data = {
            'CODIGO': codigo,
            'DESCRICAO': descricao
        }

        # Adicionar quantidades para cada horário (na ordem correta)
        for horario in horario_cols_validos:
            quantidade = row[horario] if horario in row.index else 0
            if pd.isna(quantidade):
                quantidade = 0
            else:
                try:
                    quantidade = int(float(quantidade))
                except:
                    quantidade = 0
            item_data[horario] = quantidade

        dados_processados.append(item_data)

    # Converter para DataFrame
    df_final = pd.DataFrame(dados_processados)

    # Agrupar por código e somar as quantidades (caso haja códigos duplicados)
    if len(df_final) > 0:
        colunas_agrupamento = ['CODIGO', 'DESCRICAO']
        colunas_soma = [col for col in df_final.columns if col not in colunas_agrupamento]

        df_agrupado = df_final.groupby(colunas_agrupamento, as_index=False)[colunas_soma].sum()

        # Calcular total
        df_agrupado['TOTAL'] = df_agrupado[horario_cols_validos].sum(axis=1)

        # Salvar no banco de dados
        with sqlite3.connect("database.db") as conn:
            df_agrupado.to_sql("dados", conn, if_exists="replace", index=False)
            print(f"Dados salvos: {len(df_agrupado)} itens processados")
    else:
        print("Nenhum dado válido encontrado para processar")

@bp.route("/", methods=["GET", "POST"])
def importar():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or file.filename == "":
            flash("Nenhum arquivo selecionado.", "warning")
            return redirect(request.url)

        upload_folder = "uploads"
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, file.filename)
        file.save(filepath)

        try:
            process_excel(filepath)
            flash("Planilha importada com sucesso ✅", "success")
        except Exception as exc:
            flash(f"Erro ao processar planilha: {exc}", "danger")
            print(f"Erro detalhado: {exc}")

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":

            return jsonify({"ok": True})

        return redirect(url_for("views.index"))

    return (
        "<h1>Upload Kanban</h1>"
        "<form method='post' enctype='multipart/form-data'>"
        "<input type='file' name='file' accept='.xls,.xlsx,.xlsb'>"
        "<button type='submit'>Importar</button>"
        "</form>"
    )