from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import os
import sqlite3
import pandas as pd
import re
from werkzeug.utils import secure_filename
from datetime import datetime, time

app = Flask(__name__)
app.secret_key = 'kanban_secret_key_2025'

        # Configurações
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'xls', 'xlsx', 'xlsb'}

        # Criar pasta de uploads se não existir
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
            return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def _normalize_col(col_raw):
            """Converte formatos de colunas de horário para 'HH:MM'."""
            if isinstance(col_raw, (float, int)) and not pd.isna(col_raw):
                try:
                    # Converter número decimal para tempo (formato Excel)
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

            # Verificar se já está no formato HH:MM
            match = re.fullmatch(r"(\d{1,2}):(\d{2})", col_str)
            if match:
                h, m = match.groups()
                return f"{int(h):02d}:{m}"

            return col_str

def init_db():
            """Inicializa o banco de dados."""
            conn = sqlite3.connect('database.db')
            cursor = conn.cursor()

            # Criar tabela básica se não existir
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS dados (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    CODIGO TEXT,
                    DESCRICAO TEXT,
                    TOTAL INTEGER DEFAULT 0
                )
            ''')

            # Criar tabela de saídas se não existir
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS saidas_materiais (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codigo TEXT NOT NULL,
                    horario TEXT NOT NULL,
                    quantidade_lida INTEGER NOT NULL,
                    data_saida DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.commit()
            conn.close()

def process_excel(filepath: str) -> bool:
            """Processa o arquivo Excel e salva no banco de dados."""
            try:
                print(f"Processando arquivo: {filepath}")

                # Verificar se o arquivo existe
                if not os.path.exists(filepath):
                    print(f"Arquivo não encontrado: {filepath}")
                    return False

                # Ler o arquivo Excel
                try:
                    df_raw = pd.read_excel(filepath, sheet_name=0, header=None)
                    print(f"Arquivo lido com sucesso. Shape: {df_raw.shape}")
                except Exception as e:
                    print(f"Erro ao ler arquivo Excel: {e}")
                    return False

                # A linha 4 (índice 4) contém os cabeçalhos dos horários
                header_idx = 4

                # Verificar se a linha de cabeçalho existe
                if len(df_raw) <= header_idx:
                    print(f"Arquivo não tem dados suficientes. Linhas encontradas: {len(df_raw)}")
                    return False

                header_series = df_raw.iloc[header_idx].copy()

                # Normalizar os horários no cabeçalho
                normalized_headers = []
                for i, col in enumerate(header_series):
                    if i == 0:
                        normalized_headers.append('CODIGO')
                    elif i == 1:
                        normalized_headers.append('DESCRICAO')
                    else:
                        normalized_headers.append(_normalize_col(col))

                print(f"Cabeçalhos normalizados: {normalized_headers}")

                # Criar DataFrame com os dados a partir da linha 5 (índice 5)
                df = df_raw.iloc[header_idx + 1:].copy()
                df.columns = normalized_headers

                # Limpar linhas completamente vazias
                df.dropna(how="all", inplace=True)

                # Filtrar apenas as linhas que têm código de item válido (primeira coluna)
                df = df[df.iloc[:, 0].notna() & (df.iloc[:, 0] != "")]

                print(f"Dados filtrados. Shape: {df.shape}")

                if len(df) == 0:
                    print("Nenhuma linha válida encontrada após filtros")
                    return False

                # Identificar colunas de horário (formato HH:MM) a partir da coluna M (índice 12)
                horario_cols_validos = []
                for col in df.columns[2:]:  # A partir da terceira coluna (após CODIGO e DESCRICAO)
                    if re.match(r'\d{2}:\d{2}', str(col)):
                        horario_cols_validos.append(col)

                print(f"Colunas de horário válidas encontradas: {horario_cols_validos}")

                if not horario_cols_validos:
                    print("Nenhuma coluna de horário válida encontrada")
                    return False

                # Preparar dados para salvar no banco
                dados_processados = []

                for idx, row in df.iterrows():
                    codigo = str(row['CODIGO']).strip()
                    descricao = str(row['DESCRICAO']).strip() if pd.notna(row['DESCRICAO']) else ''

                    if not codigo or codigo == 'nan':
                        continue

                    # Criar um dicionário com o código, descrição e quantidades por horário
                    item_data = {
                        'CODIGO': codigo,
                        'DESCRICAO': descricao
                    }

                    # Adicionar quantidades para cada horário
                    total = 0
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
                        total += quantidade

                    item_data['TOTAL'] = total
                    dados_processados.append(item_data)

                print(f"Dados processados: {len(dados_processados)} itens")

                # Converter para DataFrame
                if dados_processados:
                    df_final = pd.DataFrame(dados_processados)

                    # Agrupar por código e somar as quantidades (caso haja códigos duplicados)
                    colunas_agrupamento = ['CODIGO', 'DESCRICAO']
                    colunas_soma = [col for col in df_final.columns if col not in colunas_agrupamento]

                    df_agrupado = df_final.groupby(colunas_agrupamento, as_index=False)[colunas_soma].sum()

                    print(f"Dados agrupados: {len(df_agrupado)} itens únicos")

                    # Salvar no banco de dados
                    conn = sqlite3.connect('database.db')
                    cursor = conn.cursor()

                    # Dropar tabela existente
                    cursor.execute("DROP TABLE IF EXISTS dados")

                    # Limpar saídas registradas ao importar novo kanban
                    cursor.execute("DELETE FROM saidas_materiais")

                    # Criar nova tabela com colunas dinâmicas
                    colunas_sql = ['id INTEGER PRIMARY KEY AUTOINCREMENT', 'CODIGO TEXT', 'DESCRICAO TEXT']
                    for horario in horario_cols_validos:
                        colunas_sql.append(f'"{horario}" INTEGER DEFAULT 0')
                    colunas_sql.append('TOTAL INTEGER DEFAULT 0')

                    create_table_sql = f"CREATE TABLE dados ({', '.join(colunas_sql)})"
                    cursor.execute(create_table_sql)

                    # Inserir dados
                    df_agrupado.to_sql('dados', conn, if_exists='append', index=False)

                    conn.commit()
                    conn.close()

                    print(f"Dados salvos no banco: {len(df_agrupado)} itens")
                    return True
                else:
                    print("Nenhum dado válido encontrado para processar")
                    return False

            except Exception as e:
                print(f"Erro ao processar Excel: {e}")
                import traceback
                traceback.print_exc()
                return False

@app.route('/')
def index():
            return render_template('index.html')

@app.route('/upload')
def upload_page():
            return render_template('upload.html')

@app.route('/dashboard')
def dashboard():
            return render_template('dashboard.html')

@app.route('/import', methods=['GET', 'POST'])
def importar():
            if request.method == 'POST':
                print("Iniciando processo de importação...")

                # Verificar se o arquivo foi enviado
                if 'file' not in request.files:
                    print("Nenhum arquivo encontrado no request")
                    flash('Nenhum arquivo selecionado.', 'warning')
                    return redirect(request.url)

                file = request.files['file']
                print(f"Arquivo recebido: {file.filename}")

                if file.filename == '':
                    print("Nome do arquivo está vazio")
                    flash('Nenhum arquivo selecionado.', 'warning')
                    return redirect(request.url)

                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    filepath = os.path.join(UPLOAD_FOLDER, filename)

                    print(f"Salvando arquivo em: {filepath}")

                    try:
                        # Salvar arquivo
                        file.save(filepath)
                        print(f"Arquivo salvo com sucesso: {filepath}")

                        # Verificar se o arquivo foi salvo
                        if os.path.exists(filepath):
                            print(f"Arquivo confirmado no disco. Tamanho: {os.path.getsize(filepath)} bytes")
                        else:
                            print("ERRO: Arquivo não foi salvo no disco")
                            flash('Erro ao salvar arquivo temporário', 'danger')
                            return redirect(request.url)

                        # Processar arquivo
                        success = process_excel(filepath)

                        if success:
                            flash('Planilha importada com sucesso ✅', 'success')
                            print("Processamento concluído com sucesso")
                        else:
                            flash('Erro ao processar planilha: Nenhum dado válido encontrado', 'danger')
                            print("Falha no processamento")

                    except Exception as exc:
                        flash(f'Erro ao processar planilha: {exc}', 'danger')
                        print(f"Erro detalhado: {exc}")
                        import traceback
                        traceback.print_exc()

                    # Remover arquivo após processamento
                    try:
                        if os.path.exists(filepath):
                            os.remove(filepath)
                            print("Arquivo temporário removido")
                    except Exception as e:
                        print(f"Erro ao remover arquivo temporário: {e}")

                    return redirect(url_for('index'))
                else:
                    print(f"Tipo de arquivo não permitido: {file.filename}")
                    flash('Tipo de arquivo não permitido. Use .xls, .xlsx ou .xlsb', 'danger')
                    return redirect(request.url)

            return render_template('upload.html')

@app.route('/api/dados')
def dados_json():
            try:
                conn = sqlite3.connect('database.db')

                # Verificar se a tabela existe
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dados'")
                table_exists = cursor.fetchone() is not None

                if not table_exists:
                    print("Tabela 'dados' não existe")
                    conn.close()
                    return jsonify([])

                df = pd.read_sql_query("SELECT * FROM dados", conn)
                conn.close()

                # Remover coluna id se existir
                if 'id' in df.columns:
                    df = df.drop('id', axis=1)

                print(f"Retornando {len(df)} registros via API")
                return jsonify(df.to_dict(orient="records"))

            except Exception as e:
                print(f"Erro ao buscar dados: {e}")
                return jsonify([])

@app.route('/debug/database')
def debug_database():
            """Rota para debug - verificar conteúdo do banco"""
            try:
                conn = sqlite3.connect('database.db')
                cursor = conn.cursor()

                # Listar tabelas
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()

                result = {"tables": [t[0] for t in tables]}

                # Se a tabela dados existir, mostrar estrutura e alguns dados
                if 'dados' in result["tables"]:
                    cursor.execute("PRAGMA table_info(dados)")
                    columns = cursor.fetchall()
                    result["columns"] = [{"name": c[1], "type": c[2]} for c in columns]

                    cursor.execute("SELECT COUNT(*) FROM dados")
                    count = cursor.fetchone()[0]
                    result["count"] = count

                    if count > 0:
                        cursor.execute("SELECT * FROM dados LIMIT 5")
                        sample_data = cursor.fetchall()
                        result["sample"] = sample_data

                conn.close()
                return jsonify(result)

            except Exception as e:
                return jsonify({"error": str(e)})

@app.route('/api/saida-materiais', methods=['POST'])
def salvar_saida_materiais():
            """Endpoint para salvar a saída de materiais"""
            try:
                data = request.get_json()

                if not data:
                    return jsonify({"error": "Dados não fornecidos"}), 400

                horario = data.get('horario')
                itens = data.get('itens', [])

                if not horario:
                    return jsonify({"error": "Horário não fornecido"}), 400

                if not itens:
                    return jsonify({"error": "Nenhum item fornecido"}), 400

                # Conectar ao banco de dados
                conn = sqlite3.connect('database.db')
                cursor = conn.cursor()

                # Verificar se a tabela de saídas existe, se não, criar
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS saidas_materiais (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        codigo TEXT NOT NULL,
                        horario TEXT NOT NULL,
                        quantidade_lida INTEGER NOT NULL,
                        data_saida DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Inserir os itens de saída
                for codigo, quantidade in itens:
                    cursor.execute('''
                        INSERT INTO saidas_materiais (codigo, horario, quantidade_lida)
                        VALUES (?, ?, ?)
                    ''', (codigo, horario, quantidade))

                conn.commit()
                conn.close()

                return jsonify({
                    "success": True,
                    "message": f"Saída registrada com sucesso para {len(itens)} itens no horário {horario}"
                })

            except Exception as e:
                print(f"Erro ao salvar saída de materiais: {e}")
                return jsonify({"error": str(e)}), 500

@app.route('/api/saidas-registradas')
def obter_saidas_registradas():
            """Endpoint para obter as saídas já registradas"""
            try:
                conn = sqlite3.connect('database.db')
                cursor = conn.cursor()

                # Verificar se a tabela existe
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='saidas_materiais'")
                table_exists = cursor.fetchone() is not None

                if not table_exists:
                    conn.close()
                    return jsonify([])

                # Buscar todas as saídas registradas
                cursor.execute('''
                    SELECT codigo, horario, SUM(quantidade_lida) as total_lido
                    FROM saidas_materiais
                    GROUP BY codigo, horario
                ''')

                saidas = cursor.fetchall()
                conn.close()

                # Converter para formato de dicionário
                result = {}
                for codigo, horario, total_lido in saidas:
                    if codigo not in result:
                        result[codigo] = {}
                    result[codigo][horario] = total_lido

                return jsonify(result)

            except Exception as e:
                print(f"Erro ao obter saídas registradas: {e}")
                return jsonify({})

@app.route('/api/saidas-registradas-detailed')
def obter_saidas_detalhadas():
            """Saídas com descrição do item (join com tabela dados)"""
            try:
                conn = sqlite3.connect('database.db')
                cursor = conn.cursor()

                # Caso ainda não existam saídas gravadas
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='saidas_materiais'")
                if cursor.fetchone() is None:
                    conn.close()
                    return jsonify([])

                # Traz a descrição a partir da tabela dados
                cursor.execute("""
                    SELECT  sm.codigo,
                            COALESCE(d.DESCRICAO, '')      AS descricao,
                            sm.horario,
                            sm.quantidade_lida,
                            datetime(sm.data_saida,'localtime') AS data_saida
                    FROM    saidas_materiais  sm
                    LEFT JOIN dados d ON d.CODIGO = sm.codigo
                    ORDER BY sm.data_saida DESC
                """)

                rows = cursor.fetchall()
                conn.close()

                # Formata em JSON
                resultado = [
                    {
                        "codigo":           r[0],
                        "descricao":        r[1],
                        "horario":          r[2],
                        "quantidade_lida":  r[3],
                        "data_saida":       r[4]
                    }
                    for r in rows
                ]
                return jsonify(resultado)

            except Exception as e:
                print(f"Erro ao obter saídas detalhadas: {e}")
                return jsonify([])

def is_horario_completo(horario):
            """Verifica se um horário está completo (expedido >= planejado)"""
            conn = sqlite3.connect('database.db')
            cursor = conn.cursor()

            try:
                # Obter total planejado para o horário
                cursor.execute(f'SELECT SUM("{horario}") FROM dados')
                total_planejado = cursor.fetchone()[0] or 0

                # Obter total expedido para o horário
                cursor.execute("SELECT SUM(quantidade_lida) FROM saidas_materiais WHERE horario = ?", (horario,))
                total_expedido = cursor.fetchone()[0] or 0

                return total_expedido >= total_planejado
            finally:
                conn.close()

@app.route('/api/dados-completos')
def dados_completos():
            try:
                conn = sqlite3.connect('database.db')
                cursor = conn.cursor()

                # Verificar se a tabela 'dados' existe
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dados'")
                if not cursor.fetchone():
                    return jsonify({
                        "total_planejado": 0,
                        "total_expedido": 0,
                        "total_horarios": 0,
                        "horarios_concluidos": 0,
                        "status_horarios": [],
                        "top_itens": [],
                        "eficiencia": {
                            "total_leituras": 0,
                            "tempo_medio": 0,
                            "taxa_erros": 0,
                            "ultimas_leituras": []
                        },
                        "tendencia": {
                            "meta": 0,
                            "pontos": []
                        }
                    })

                # 1. Visão Geral
                # Total planejado (soma da coluna TOTAL da tabela dados)
                cursor.execute("SELECT SUM(TOTAL) FROM dados")
                total_planejado = cursor.fetchone()[0] or 0

                # Total expedido (soma de todas as quantidades_lidas da tabela saidas_materiais do dia)
                cursor.execute("SELECT SUM(quantidade_lida) FROM saidas_materiais WHERE date(data_saida) = date('now')")
                total_expedido = cursor.fetchone()[0] or 0

                # Total de horários: colunas de horário na tabela dados
                cursor.execute("PRAGMA table_info(dados)")
                columns = cursor.fetchall()
                horario_columns = [col[1] for col in columns if re.match(r"^\d{2}:\d{2}$", col[1])]
                total_horarios = len(horario_columns)

                # Horários concluídos: quantos horários têm expedido >= planejado
                horarios_concluidos = 0
                for horario in horario_columns:
                    if is_horario_completo(horario):
                        horarios_concluidos += 1

                # 2. Status por Horário
                status_horarios = []
                for horario in horario_columns:
                    cursor.execute(f'SELECT SUM("{horario}") FROM dados')
                    planejado = cursor.fetchone()[0] or 0

                    cursor.execute("SELECT SUM(quantidade_lida) FROM saidas_materiais WHERE horario = ?", (horario,))
                    expedido = cursor.fetchone()[0] or 0

                    percentual = round((expedido / planejado) * 100, 1) if planejado > 0 else 0.0

                    # Determinar status com 3 estados
                    status = "Concluído" if expedido >= planejado else "Parcial" if expedido > 0 else "Pendente"

                    status_horarios.append({
                        "horario": horario,
                        "planejado": planejado,
                        "expedido": expedido,
                        "percentual": percentual,
                        "status": status
                    })

                # 3. TOP 5 Itens
                cursor.execute('''
                    SELECT codigo, SUM(quantidade_lida) as total_expedido
                    FROM saidas_materiais
                    WHERE date(data_saida) = date('now')
                    GROUP BY codigo
                    ORDER BY total_expedido DESC
                    LIMIT 5
                ''')
                top_itens_rows = cursor.fetchall()
                top_itens = [{"codigo": row[0], "total_expedido": row[1]} for row in top_itens_rows]

                # 4. Eficiência de Leitura (simulada)
                eficiencia = {
                    "total_leituras": 42,  # Simulado
                    "tempo_medio": 5.2,    # Simulado (em segundos)
                    "taxa_erros": 2.4,     # Simulado (em percentual)
                    "ultimas_leituras": [   # Simulado
                        {"codigo": "ITEM001", "horario": "10:30", "quantidade": 15, "status": "Sucesso"},
                        {"codigo": "ITEM045", "horario": "10:25", "quantidade": 8, "status": "Sucesso"},
                        {"codigo": "ITEM123", "horario": "10:15", "quantidade": 12, "status": "Erro"},
                        {"codigo": "ITEM087", "horario": "10:10", "quantidade": 10, "status": "Sucesso"}
                    ]
                }

                # 5. Tendência de Expedição
                # Meta diária é o total planejado
                meta = total_planejado

                # Obter as saídas agrupadas por hora (acumulado)
                cursor.execute('''
                    SELECT 
                        strftime('%H:00', data_saida) as hora,
                        SUM(quantidade_lida) as total
                    FROM saidas_materiais
                    WHERE date(data_saida) = date('now')
                    GROUP BY hora
                    ORDER BY hora
                ''')
                saidas_por_hora = cursor.fetchall()

                # Inicializar o acumulado
                acumulado = 0
                pontos = []

                # Criar uma lista de horas do dia (das 08:00 às 18:00, por exemplo)
                horas = [f"{h:02d}:00" for h in range(8, 19)]

                # Para cada hora, somar ao acumulado
                for hora in horas:
                    # Encontrar o total para esta hora, se existir
                    total_hora = 0
                    for row in saidas_por_hora:
                        if row[0] == hora:
                            total_hora = row[1]
                            break

                    acumulado += total_hora
                    pontos.append({
                        "hora": hora,
                        "realizado": acumulado
                    })

                tendencia = {
                    "meta": meta,
                    "pontos": pontos
                }

                conn.close()

                return jsonify({
                    "total_planejado": total_planejado,
                    "total_expedido": total_expedido,
                    "total_horarios": total_horarios,
                    "horarios_concluidos": horarios_concluidos,
                    "status_horarios": status_horarios,
                    "top_itens": top_itens,
                    "eficiencia": eficiencia,
                    "tendencia": tendencia
                })

            except Exception as e:
                print(f"Erro ao buscar dados completos: {e}")
                import traceback
                traceback.print_exc()
                return jsonify({"error": str(e)}), 500

@app.route('/api/grafico-codigos')
def grafico_codigos():
            """Endpoint para dados do gráfico de códigos de modelo"""
            try:
                conn = sqlite3.connect('database.db')
                cursor = conn.cursor()

                # Verificar se a tabela 'dados' existe
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dados'")
                if not cursor.fetchone():
                    conn.close()
                    return jsonify([])

                # Obter todos os dados da tabela
                df = pd.read_sql_query("SELECT * FROM dados", conn)

                # Obter saídas registradas
                cursor.execute('''
                    SELECT codigo, SUM(quantidade_lida) as total_enviado
                    FROM saidas_materiais
                    GROUP BY codigo
                ''')
                saidas = cursor.fetchall()
                conn.close()

                # Criar dicionário de saídas
                saidas_dict = {}
                for codigo, total_enviado in saidas:
                    saidas_dict[codigo] = total_enviado

                # Processar dados para o gráfico
                grafico_data = []

                for _, row in df.iterrows():
                    codigo = row['CODIGO']
                    total_planejado = row['TOTAL'] if 'TOTAL' in row else 0
                    total_enviado = saidas_dict.get(codigo, 0)
                    pendente = max(0, total_planejado - total_enviado)

                    # Só incluir itens que têm quantidade planejada > 0
                    if total_planejado > 0:
                        grafico_data.append({
                            'codigo': codigo,
                            'total_planejado': total_planejado,
                            'total_enviado': total_enviado,
                            'pendente': pendente
                        })

                # Ordenar por total planejado (maior primeiro)
                grafico_data.sort(key=lambda x: x['total_planejado'], reverse=True)

                return jsonify(grafico_data)

            except Exception as e:
                print(f"Erro ao buscar dados do gráfico: {e}")
                return jsonify([])

if __name__ == '__main__':
            init_db()
            print("Sistema Kanban iniciado!")
            print("Acesse: http://localhost:5000")
            app.run(host='0.0.0.0', port=5000, debug=True)

@app.route('/api/status-celulas')
def status_celulas():
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()

        dados = pd.read_sql_query("SELECT * FROM dados", conn)
        dados.set_index('CODIGO', inplace=True)

        saidas = pd.read_sql_query("""
            SELECT codigo, horario, SUM(quantidade_lida) as quantidade_lida
            FROM saidas_materiais
            GROUP BY codigo, horario
        """, conn)

        conn.close()

        status = {}
        for _, row in saidas.iterrows():
            codigo = row['codigo']
            horario = row['horario']
            lida = row['quantidade_lida']
            esperada = dados.at[codigo, horario] if horario in dados.columns else 0

            if codigo not in status:
                status[codigo] = {}

            if lida >= esperada and esperada > 0:
                status[codigo][horario] = 'verde'
            elif lida > 0:
                status[codigo][horario] = 'laranja'
            else:
                status[codigo][horario] = 'amarelo'

        return jsonify(status)
