import math
import re
import statistics
import unicodedata
from datetime import datetime, timezone

def normalizar_texto(texto):
    if texto is None:
        return ""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^A-Za-z0-9.-]", "", texto)
    return re.sub(r"\s+", " ", texto).strip()

def a_numero(valor):
    try:
        if valor is None or isinstance(valor, bool):
            return None
        x = float(valor)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None

def limpiar(payload):
    reporte = {
        "registros_entrada": len(payload),
        "descartados_sin_precio": 0,
        "duplicados_eliminados": 0,
        "imputaciones": 0,
        "nombres_normalizados": 0
    }
    vistos, limpios = set(), []

    for r in payload:
        if not isinstance(r, dict):
            reporte["descartados_sin_precio"] += 1
            continue
        precio = a_numero(r.get("current_price"))
        if precio is None or precio <= 0:
            reporte["descartados_sin_precio"] += 1
            continue
        rid = str(r.get("id") or r.get("symbol") or "").strip().lower()
        if not rid or rid in vistos:
            reporte["duplicados_eliminados"] += 1
            continue
        vistos.add(rid)

        nombre = normalizar_texto(r.get("name"))
        if nombre != r.get("name"):
            reporte["nombres_normalizados"] += 1

        limpios.append({
            "id": rid,
            "symbol": normalizar_texto(r.get("symbol")).upper(),
            "name": nombre,
            "price": precio,
            "market_cap": a_numero(r.get("market_cap")),
            "volume": a_numero(r.get("total_volume")),
            "change_24h": a_numero(r.get("price_change_percentage_24h")),
            "high_24h": a_numero(r.get("high_24h")),
            "low_24h": a_numero(r.get("low_24h"))
        })

    for campo in ("market_cap", "volume", "change_24h"):
        vals = [x[campo] for x in limpios if x[campo] is not None]
        med = statistics.median(vals) if vals else 0.0
        for x in limpios:
            if x[campo] is None:
                x[campo] = med
                x.setdefault("imputados", []).append(campo)
                reporte["imputaciones"] += 1

    for x in limpios:
        if x["high_24h"] is None:
            x["high_24h"] = x["price"]
        if x["low_24h"] is None:
            x["low_24h"] = x["price"]

    reporte["registros_salida"] = len(limpios)
    return limpios, reporte

def etiqueta_momentum(cambio):
    if cambio >= 3: return "ALCISTA_FUERTE"
    if cambio >= 0.5: return "ALCISTA"
    if cambio > -0.5: return "LATERAL"
    if cambio > -3: return "BAJISTA"
    return "BAJISTA_FUERTE"

def etiqueta_volatilidad(rango_pct):
    if rango_pct >= 8: return "ALTA"
    if rango_pct >= 3: return "MEDIA"
    return "BAJA"

def score_riesgo(rango_pct, cambio, liquidez):
    s = min(rango_pct * 4, 50) + min(abs(cambio) * 3, 30) + 20 * (1 - min(liquidez * 10, 1))
    return round(max(0, min(100, s)), 1)

def kmeans_1d(valores, k=3, iteraciones=50):
    if len(valores) < k:
        return [0] * len(valores), sorted(set(valores))
    orden = sorted(valores)
    cent = [orden[int((i + 0.5) * len(orden) / k)] for i in range(k)]
    asign = [0] * len(valores)
    for _ in range(iteraciones):
        nuevo = [min(range(k), key=lambda j: abs(v - cent[j])) for v in valores]
        if nuevo == asign:
            break
        asign = nuevo
        for j in range(k):
            miembros = [v for v, a in zip(valores, asign) if a == j]
            if miembros:
                cent[j] = sum(miembros) / len(miembros)
    return asign, cent

def minar(limpios):
    nombres_cluster = ["Capitalizacion_BAJA", "Capitalizacion_MEDIA", "Capitalizacion_ALTA"]
    logs = [math.log10(x["market_cap"]) if x["market_cap"] > 0 else 0.0 for x in limpios]
    asign, cent = kmeans_1d(logs, 3)
    rank = {j: pos for pos, j in enumerate(sorted(range(len(cent)), key=lambda j: cent[j]))}

    resultados = []
    for x, a in zip(limpios, asign):
        rango = ((x["high_24h"] - x["low_24h"]) / x["price"]) * 100
        liquidez = x["volume"] / x["market_cap"] if x["market_cap"] else 0.0
        resultados.append({
            "id": x["id"], "symbol": x["symbol"], "name": x["name"],
            "price_usd": x["price"],
            "change_24h_pct": round(x["change_24h"], 3),
            "range_24h_pct": round(rango, 3),
            "volume_marketcap_ratio": round(liquidez, 4),
            "momentum": etiqueta_momentum(x["change_24h"]),
            "volatilidad": etiqueta_volatilidad(rango),
            "risk_score": score_riesgo(rango, x["change_24h"], liquidez),
            "cluster": nombres_cluster[rank[a]] if len(cent) == 3 else f"cluster_{a}",
            "datos_imputados": x.get("imputados", [])
        })
    resultados.sort(key=lambda r: r["risk_score"], reverse=True)
    return resultados

def resumen(resultados):
    if not resultados:
        return {}
    cambios = [r["change_24h_pct"] for r in resultados]
    conteo = lambda c: {k: sum(1 for r in resultados if r[c] == k) for k in set(r[c] for r in resultados)}
    return {
        "momentum": conteo("momentum"),
        "volatilidad": conteo("volatilidad"),
        "clusters": conteo("cluster"),
        "cambio_promedio_24h_pct": round(statistics.mean(cambios), 3),
        "mayor_riesgo": resultados[0]["symbol"],
        "menor_riesgo": resultados[-1]["symbol"]
    }

def procesar(payload, fuente="desconocida"):
    limpios, rep = limpiar(payload)
    res = minar(limpios)
    return {
        "status": "ok",
        "procesado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": fuente,
        "limpieza": rep,
        "resumen": resumen(res),
        "resultados": res
    }