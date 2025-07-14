import pandas as pd
import sqlite3
from flask import Blueprint, render_template, jsonify

bp = Blueprint("views", __name__)

@bp.route("/")
def index():
    return render_template("index.html")

@bp.route("/api/dados")
def dados_json():
    conn = sqlite3.connect("database.db")
    df = pd.read_sql_query("SELECT * FROM dados", conn)
    conn.close()
    return jsonify(df.to_dict(orient="records"))
