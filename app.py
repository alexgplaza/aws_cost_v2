
# app.py
from flask import Flask, render_template, request, jsonify, Response
import pandas as pd
import plotly.graph_objs as go
import plotly
import json
import numpy as np
from datetime import datetime
from plotly.colors import qualitative as q


app = Flask(__name__)

# Datos del Fichero 1 (detalle) que alimentan gráficos/comparativas/presupuesto
original_df = None


@app.route("/", methods=["GET", "POST"])
## prueba
@app.route("/", methods=["GET", "POST"])
def index(): 
    """
    Página principal prueba:
      - POST: recibe 2 CSVs (file_graph y file_table).
        * file_graph -> gráficos/comparativas/presupuesto (detalle)
        * file_table -> primera tabla (resumen, agregado multi-mes por Account)
      - GET: muestra formulario si no hay datos.
    """
    global original_df

    table_data = None
    months = []
    periodo = None
    graphJSON = None
    accounts_list = []

    if request.method == "POST":
        file_graph = request.files.get("file_graph")  # detalle
        file_table = request.files.get("file_table")  # resumen (tabla)

        if not file_graph or not file_table:
            app.logger.warning("Faltan uno o ambos ficheros en el POST.")
            return render_template(
                "index.html",
                table_data=None,
                months=[],
                periodo=None,
                graphJSON=None,
                accounts=[]
            )

        # =======================
        # 1) CSV 1 (DETALLE) -> gráficos/comparativa/presupuesto
        # =======================
        try:
            df = pd.read_csv(file_graph, on_bad_lines='skip')
        except Exception as ex:
            app.logger.exception("Error leyendo file_graph (detalle)")
            return f"Error leyendo el CSV de detalle: {ex}", 400

        for col in ['Usage Amount', 'Tax', 'Edp Discount']:
            if col not in df.columns:
                app.logger.warning(f"Columna faltante en detalle: {col} (se pone 0)")
                df[col] = 0
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        if "Usage Start Date" not in df.columns:
            app.logger.error("Falta 'Usage Start Date' en el CSV de detalle.")
            return "El CSV de detalle debe contener 'Usage Start Date'.", 400

        df["Usage Start Date"] = df["Usage Start Date"].astype(str).str.strip()
        df["Month"] = pd.to_datetime(df["Usage Start Date"], errors="coerce") \
            .dt.to_period("M").astype(str)   # YYYY-MM

        # Periodo (basado en detalle por si el resumen no lo trae bien)
        meses_det = sorted(df["Month"].dropna().unique())
        if meses_det:
            periodo = f"{meses_det[0]} a {meses_det[-1]}"

        # Guardar para endpoints /compare, /account_graph y /fiscal_usage
        original_df = df.copy()

        # Base de costes por Account y Mes (del CSV 1)
        df_graph = original_df.copy()
        df_graph["Total"] = df_graph["Usage Amount"] + df_graph["Tax"] + df_graph["Edp Discount"]
        grouped = df_graph.groupby(["Month", "Account"])["Total"].sum().reset_index()

        # =======================
        # 2) CSV 2 (RESUMEN) -> Tabla + Overheads por mes
        # =======================
        try:
            df_table = pd.read_csv(file_table, on_bad_lines='skip')
        except Exception as ex:
            app.logger.exception("Error leyendo file_table (resumen)")
            return f"Error leyendo el CSV de resumen: {ex}", 400

        # --- Tabla agregada por Account (lo que ya tenías) ---
        needed = [
            "Account",
            "Usage",
            "Tax",
            "Edp Discount",
            "PCS Enabler Cost",
            "Operations & Security",
            "Account Enablement Fee",
            "Total Cost",
        ]
        for col in needed:
            if col not in df_table.columns:
                app.logger.warning(f"Columna faltante en resumen: {col} (se pone 0)")
                df_table[col] = 0

        numeric_cols = [c for c in needed if c != "Account"]
        for col in numeric_cols:
            df_table[col] = pd.to_numeric(df_table[col], errors='coerce').fillna(0)

        summary = df_table.groupby("Account", as_index=False)[numeric_cols].sum()
        summary[numeric_cols] = summary[numeric_cols].round(2)

        grand = {"Account": "Grand Total"}
        for col in numeric_cols:
            grand[col] = round(summary[col].sum(), 2)
        summary = pd.concat([summary, pd.DataFrame([grand])], ignore_index=True)
        table_data = summary.to_dict(orient="records")

        # --- Periodo con Month del CSV 2 (si viene en abreviaturas ES) ---
        #     Y normalizamos a YYYY-MM para poder alinear el eje X del gráfico
        ### NUEVO: normalización del campo Month (CSV 2) a YYYY-MM
        month_norm = None
        if "Month" in df_table.columns:
            meses_map = {
                "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
                "jul": 7, "ago": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dic": 12
            }

            def to_yyyymm(mes_str):
                # Acepta "ene 2026" / "sept 2025" (insensible a mayúsculas)
                if not isinstance(mes_str, str):
                    return None
                parts = mes_str.strip().split()
                if len(parts) != 2:
                    return None
                abrev, year = parts[0].lower(), parts[1]
                if abrev not in meses_map:
                    return None
                try:
                    y, m = int(year), int(meses_map[abrev])
                    return f"{y:04d}-{m:02d}"
                except Exception:
                    return None

            df_table["MonthNorm"] = df_table["Month"].astype(str).map(to_yyyymm)
            # Periodo (si hay datos válidos)
            valid_norm = df_table["MonthNorm"].dropna().unique().tolist()
            if valid_norm:
                months_sorted_norm = sorted(valid_norm)              # YYYY-MM orden lexicográfico == cronológico
                periodo = f"{months_sorted_norm[0]} a {months_sorted_norm[-1]}"
                month_norm = months_sorted_norm

        # =======================
        # 3) Construcción del stacked con OVERHEADS
        # =======================

        # Eje X final: unión de meses del CSV 1 (detalle) y CSV 2 (resumen normalizado)
        months_detail = sorted(grouped["Month"].dropna().unique().tolist())
        months_over = month_norm if month_norm else []
        all_months = sorted(set(months_detail).union(set(months_over)))

        # Si por lo que sea no hay month_norm (CSV 2 sin Month), seguimos con months_detail
        if not all_months:
            all_months = months_detail

        # Trazas por Account (como antes), pero sobre 'all_months'
        accounts = grouped["Account"].dropna().unique()
        #preset_colors = ["#1f77b4", "#9467bd", "#17becf"]

        big_palette = (
            q.Dark24 + q.Set3 + q.Bold + q.Safe + q.Pastel + q.D3 + q.Antique  # orden a tu gusto
        )

        colors = {acc: big_palette[i % len(big_palette)] for i, acc in enumerate(accounts)}

        bars = []
        for acc in accounts:
            y_vals = []
            for m in all_months:
                v = grouped[(grouped["Account"] == acc) & (grouped["Month"] == m)]["Total"].sum()
                y_vals.append(v)
            bars.append(go.Bar(name=acc, x=all_months, y=y_vals, marker=dict(color=colors.get(acc))))

        # --- Overheads mensuales desde CSV 2 (resumen): sumatorio por MonthNorm ---
        ### NUEVO: sumarización mensual de los 3 conceptos en CSV 2
        overhead_cols = ["PCS Enabler Cost", "Operations & Security", "Account Enablement Fee"]
        if "MonthNorm" in df_table.columns:
            over_gr = df_table.groupby("MonthNorm")[overhead_cols].sum()
            # Aseguramos todas las categorías de 'all_months'
            over_gr = over_gr.reindex(all_months, fill_value=0)

            # Añadimos 3 trazas nuevas al stacked
            bars.append(go.Bar(
                name="Overhead: PCS Enabler Cost",
                x=all_months,
                y=over_gr["PCS Enabler Cost"].tolist(),
                marker=dict(color="#8c564b")  # marrón
            ))
            bars.append(go.Bar(
                name="Overhead: Operations & Security",
                x=all_months,
                y=over_gr["Operations & Security"].tolist(),
                marker=dict(color="#e377c2")  # rosa
            ))
            bars.append(go.Bar(
                name="Overhead: Account Enablement Fee",
                x=all_months,
                y=over_gr["Account Enablement Fee"].tolist(),
                marker=dict(color="#7f7f7f")  # gris
            ))
        else:
            # No hay Month en CSV 2 -> no podemos repartir por mes (no añadimos trazas)
            app.logger.warning("CSV de resumen sin columna Month/MonthNorm; no se añaden overheads al gráfico.")

        # Recalcular percentiles P50/P90 con cuentas + overheads
        ### NUEVO: percentiles incluyendo overheads
        accounts_monthly_total = grouped.groupby("Month")["Total"].sum().reindex(all_months, fill_value=0).values
        overhead_monthly_total = np.zeros(len(all_months))
        if "MonthNorm" in df_table.columns:
            overhead_monthly_total = over_gr.sum(axis=1).values  # suma de los 3 conceptos por mes

        monthly_totals = accounts_monthly_total + overhead_monthly_total
        if len(monthly_totals) > 0:
            p50 = np.percentile(monthly_totals, 50)
            p90 = np.percentile(monthly_totals, 90)
            bars.append(go.Scatter(
                x=all_months, y=[p50] * len(all_months),
                mode='lines', name='Percentil 50',
                line=dict(color='blue', dash='dash')
            ))
            bars.append(go.Scatter(
                x=all_months, y=[p90] * len(all_months),
                mode='lines', name='Percentil 90',
                line=dict(color='red', dash='dash')
            ))

        layout = go.Layout(
            barmode='stack',
            title='Monthly Cost per AWS Account',
            xaxis=dict(title='Month', type='category'),
            yaxis=dict(title='Cost €'),
            legend=dict(orientation="h", y=-0.25)  # bajamos un poco la leyenda
        )
        fig = go.Figure(data=bars, layout=layout)
        graphJSON = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

        # Para el resto de bloques (selector de cuentas y comparativa)
        months = all_months
        accounts_list = sorted(df_graph["Account"].dropna().unique().tolist())

    return render_template(
        "index.html",
        table_data=table_data,
        months=months,
        periodo=periodo,
        graphJSON=graphJSON,
        accounts=accounts_list
    )



@app.route("/compare", methods=["POST"])
def compare():
    """
    Devuelve para 2 meses: diferencia absoluta y % por Account.
    Usa original_df (detalle).
    """
    global original_df
    data = request.get_json()
    current = data.get("current")
    compare = data.get("compare")

    if original_df is None or not current or not compare:
        return jsonify([])

    df = original_df.copy()
    df["Total"] = df["Usage Amount"] + df["Tax"] + df["Edp Discount"]
    grouped = df.groupby(["Account", "Month"])["Total"].sum().reset_index()

    current_df = grouped[grouped["Month"] == current].set_index("Account")["Total"]
    compare_df = grouped[grouped["Month"] == compare].set_index("Account")["Total"]

    all_accounts = current_df.index.union(compare_df.index)
    diff_df = pd.DataFrame(index=all_accounts)
    diff_df["Current"] = current_df
    diff_df["Compare"] = compare_df
    diff_df = diff_df.fillna(0)

    def pct(curr, comp):
        if comp == 0:
            return 0.0
        return round((curr - comp) / abs(comp) * 100, 2)

    diff_df["Difference"] = (diff_df["Current"] - diff_df["Compare"]).round(2)
    diff_df["Percentage"] = [pct(cu, co) for cu, co in zip(diff_df["Current"], diff_df["Compare"])]
    diff_df = diff_df.reset_index()

    return jsonify(diff_df[["Account", "Difference", "Percentage"]].to_dict(orient="records"))


@app.route("/account_graph", methods=["POST"])
def account_graph():
    """
    Devuelve JSON con:
      - stacked: barras apiladas por servicio/mes
      - donut: distribución último mes
    Usa original_df (detalle).
    """
    global original_df
    selected = request.json.get("account")
    if not selected or original_df is None:
        return jsonify({})

    df = original_df.copy()
    df["Total"] = df["Usage Amount"] + df["Tax"] + df["Edp Discount"]
    df["Month"] = pd.to_datetime(df["Usage Start Date"], errors="coerce").dt.to_period("M").astype(str)
    df = df[df["Account"] == selected]

    if df.empty:
        return jsonify({})

    # Agrupar por mes y servicio
    grouped = df.groupby(["Month", "Service"])["Total"].sum().reset_index()

    # Top servicios
    top_services = grouped.groupby("Service")["Total"].sum().nlargest(10).index.tolist()
    grouped["Service"] = grouped["Service"].apply(lambda s: s if s in top_services else "Others")
    grouped = grouped.groupby(["Month", "Service"])["Total"].sum().reset_index()

    months = sorted(grouped["Month"].unique())
    services = grouped["Service"].unique()

    data = []
    for service in services:
        y_vals = [grouped[(grouped["Service"] == service) & (grouped["Month"] == m)]["Total"].sum()
                  for m in months]
        data.append(go.Bar(name=service, x=months, y=y_vals))

    layout = go.Layout(
        barmode="stack",
        title=f"Monthly Breakdown Cost per Service for {selected}",
        xaxis=dict(title="Month", type="category"),
        yaxis=dict(title="Cost €"),
        legend=dict(orientation="h", y=-0.3)
    )
    fig = go.Figure(data=data, layout=layout)

    # Donut último mes
    latest_month = df["Month"].max()
    df_last_month = df[df["Month"] == latest_month]
    donut_data = df_last_month.groupby("Service")["Total"].sum().reset_index().sort_values("Total", ascending=False)

    if len(donut_data) > 5:
        top_5 = donut_data.head(5)
        others_total = donut_data.iloc[5:]["Total"].sum()
        donut_data = pd.concat([top_5, pd.DataFrame([{"Service": "Others", "Total": others_total}])], ignore_index=True)

    donut_data["Total"] = pd.to_numeric(donut_data["Total"], errors='coerce').fillna(0)
    donut_fig = go.Figure(data=[go.Pie(
        labels=donut_data["Service"].tolist(),
        values=donut_data["Total"].astype(float).tolist(),
        hole=0.5,
        textinfo="label+percent",
        hovertemplate="%{label}: %{value:.2f} € (%{percent})"
    )])
    donut_fig.update_layout(title=f"Service Cost Distributions for {selected} ({latest_month})")

    combined_graphs = {
        "stacked": json.loads(plotly.io.to_json(fig)),
        "donut": json.loads(plotly.io.to_json(donut_fig))
    }
    return Response(json.dumps(combined_graphs, cls=plotly.utils.PlotlyJSONEncoder),
                    mimetype="application/json")


@app.route("/fiscal_usage", methods=["POST"])
def fiscal_usage():
    """
    Calcula gasto total del año fiscal (abril-actual -> marzo-siguiente) contra un presupuesto dado.
    Usa original_df (detalle).
    """
    global original_df
    if original_df is None:
        return jsonify({"error": "No data uploaded"}), 400

    data = request.get_json()
    budget = data.get("budget")
    try:
        budget = float(budget)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid budget value"}), 400

    now = datetime.now()
    fiscal_start = datetime(now.year, 4, 1)
    fiscal_end = datetime(now.year + 1, 3, 31)

    df = original_df.copy()
    df["DateParsed"] = pd.to_datetime(df["Usage Start Date"], errors="coerce")
    df_fiscal = df[(df["DateParsed"] >= fiscal_start) & (df["DateParsed"] <= fiscal_end)]
    df_fiscal["Total"] = df_fiscal["Usage Amount"] + df_fiscal["Tax"] + df_fiscal["Edp Discount"]
    total_spent = df_fiscal["Total"].sum()
    used_pct = round((total_spent / budget) * 100, 2) if budget > 0 else 0.0

    return jsonify({
        "used_pct": used_pct,
        "total_spent": round(total_spent, 2)
    })


if __name__ == "__main__":
    # Lanza el servidor en 0.0.0.0:5001
    # Si algo falla al importar el módulo, no llegarás aquí: revisa el traceback.
    app.logger.setLevel("INFO")
    app.logger.info("Arrancando servidor Flask en http://0.0.0.0:5001 ...")
    app.run(host="0.0.0.0", port=5001, debug=True)
