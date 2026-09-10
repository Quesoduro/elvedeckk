from collections import deque
from datetime import datetime
import html
import json
import re
import threading
import time
import urllib.parse
import requests

TELEGRAM_BOT_TOKEN = "8850513477:AAGNCp5m4q5-bFs1aZ5RvNbCgPKNCOLcfX0"
INTERVALO_MINUTOS = 30
MAX_HISTORIAL = 10

CATEGORIAS = {
    "Pets": "https://amvgg.com/values/pets",
    "Eggs": "https://amvgg.com/values/eggs",
    "Vehicles": "https://amvgg.com/values/vehicles",
    "Toys": "https://amvgg.com/values/toys",
    "Pet Wear": "https://amvgg.com/values/petwear",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
        " Safari/537.36"
    )
}

TRADUCCIONES = {
    "reno artico": "Arctic Reindeer",
    "reno ártico": "Arctic Reindeer",
    "perro azul": "Blue Dog",
    "gato rosado": "Pink Cat",
    "dragon de murcielago": "Bat Dragon",
    "dragón de murciélago": "Bat Dragon",
    "jirafa": "Giraffe",
    "unicornio de la sombra": "Shadow Dragon",
    "dragon de sombra": "Shadow Dragon",
    "dragón de sombra": "Shadow Dragon",
    "cuervo": "Crow",
    "buho": "Owl",
    "búho": "Owl",
    "helado": "Frost Dragon",
    "dragon de hielo": "Frost Dragon",
    "dragón de hielo": "Frost Dragon",
}

historial_db = {}
alertas_db = []
inventarios_db = {}
categoria_map = {}
usuarios_activos = set()

db_lock = threading.RLock()
cargando_datos = False


def clean_text(text):
  """Escapa caracteres conflictivos para evitar errores de parseo HTML en Telegram."""
  if not text:
    return ""
  return html.escape(str(text))


def send_telegram_message(chat_id, text):
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
  try:
    res = requests.post(url, json=payload, timeout=8)
    if not res.ok:
      print(f"⚠️ Telegram devolvió error: {res.text}")
  except Exception as e:
    print(f"❌ Error al enviar mensaje a Telegram: {e}")


def send_telegram_photo(chat_id, photo_url, caption=""):
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
  payload = {
      "chat_id": chat_id,
      "photo": photo_url,
      "caption": caption,
      "parse_mode": "HTML",
  }
  try:
    res = requests.post(url, json=payload, timeout=12)
    if not res.ok:
      print(f"⚠️ Telegram devolvió error al enviar foto: {res.text}")
  except Exception as e:
    print(f"❌ Error al enviar foto a Telegram: {e}")


def fetch_category_items(url):
  try:
    res = requests.get(url, headers=HEADERS, timeout=10)
    if res.status_code != 200:
      return {}
    clean_html = res.text.replace(r"\"", '"')
    pattern = re.compile(r'\{"id":"[a-f0-9]{24}",.*?"name":"[^"]+".*?\}')
    matches = pattern.findall(clean_html)
    items = {}
    for match in matches:
      try:
        data = json.loads(match)
        name = data.get("name")
        if not name:
          continue
        val_reg = float(data.get("regularValue") or data.get("fValue") or 0.0)
        val_fr = float(data.get("frValue") or val_reg)
        val_nfr = float(data.get("nfrValue") or 0.0)
        val_mfr = float(data.get("mfrValue") or 0.0)
        items[name] = {
            "REG": val_reg,
            "FR": val_fr,
            "NFR": val_nfr,
            "MFR": val_mfr,
        }
      except Exception:
        continue
    return items
  except Exception as e:
    print(f"⚠️ Error en {url}: {e}")
    return {}


def verificar_alertas():
  global alertas_db
  with db_lock:
    alertas_activas = list(alertas_db)
    alertas_restantes = []

    for alerta in alertas_activas:
      chat_id = alerta["chat_id"]
      item_name = alerta["item"]
      variant = alerta["variant"]
      cond = alerta["cond"]
      target = alerta["target"]

      item_data = historial_db.get(item_name)
      if not item_data or variant not in item_data or not item_data[variant]:
        alertas_restantes.append(alerta)
        continue

      valor_actual = item_data[variant][-1]["value"]
      cumplida = False

      if cond == ">" and valor_actual > target:
        cumplida = True
      elif cond == "<" and valor_actual < target:
        cumplida = True
      elif cond == ">=" and valor_actual >= target:
        cumplida = True
      elif cond == "<=" and valor_actual <= target:
        cumplida = True

      if cumplida:
        msg = (
            "🚨 <b>¡ALERTA DE PRECIO ALCANZADA!</b> 🚨\n\n"
            f"🐾 <b>Pet:</b> {clean_text(item_name)}\n"
            f"🧪 <b>Variante:</b> {clean_text(variant)}\n"
            f"📈 <b>Condición:</b> {clean_text(cond)} {target}\n"
            f"💰 <b>Valor actual:</b> <code>{valor_actual}</code>"
        )
        send_telegram_message(chat_id, msg)
      else:
        alertas_restantes.append(alerta)

    alertas_db = alertas_restantes


def detectar_oportunidades_y_difundir():
  with db_lock:
    top_msg = generar_top_cambios()

    for chat_id in usuarios_activos:
      send_telegram_message(
          chat_id, f"⏰ <b>ACTUALIZACIÓN DE MERCADO (30 MIN)</b>\n\n{top_msg}"
      )

      for item_name, data in historial_db.items():
        for variant, deque_vals in data.items():
          hist = list(deque_vals)
          if len(hist) >= 2:
            val_act = hist[-1]["value"]
            val_prev = hist[-2]["value"]
            if val_prev > 0:
              pct = ((val_act - val_prev) / val_prev) * 100
              if abs(pct) >= 15.0:
                tipo = (
                    "🚀 <b>OPORTUNIDAD DE SUBIDA</b>"
                    if pct > 0
                    else "📉 <b>OPORTUNIDAD DE CAÍDA (DESCUENTO)</b>"
                )
                msg_op = (
                    f"⚡ <b>¡ALERTA DE OPORTUNIDAD!</b> ⚡\n\n"
                    f"{tipo}\n"
                    f"🐾 <b>Item:</b> {clean_text(item_name)} ({clean_text(variant)})\n"
                    f"📊 <b>Variación:</b> <b>{pct:+.2f}%</b>\n"
                    f"💵 <b>Precio anterior:</b> <code>{val_prev}</code> ➔ <b>Nuevo:</b> <code>{val_act}</code>"
                )
                send_telegram_message(chat_id, msg_op)


def actualizar_base_de_datos():
  global cargando_datos
  cargando_datos = True
  now_str = datetime.now().strftime("%H:%M - %d/%m/%Y")
  print(f"\n[🔄 {now_str}] Sincronizando datos de AMVGG...")
  conteo = 0

  for cat_name, url in CATEGORIAS.items():
    items_actuales = fetch_category_items(url)
    with db_lock:
      for name, valores in items_actuales.items():
        categoria_map[name] = cat_name
        if name not in historial_db:
          historial_db[name] = {
              "REG": deque(maxlen=MAX_HISTORIAL),
              "FR": deque(maxlen=MAX_HISTORIAL),
              "NFR": deque(maxlen=MAX_HISTORIAL),
              "MFR": deque(maxlen=MAX_HISTORIAL),
          }
        for var in ["REG", "FR", "NFR", "MFR"]:
          historial_db[name][var].append(
              {"timestamp": now_str, "value": valores[var]}
          )
        conteo += 1

  cargando_datos = False
  print(f"✅ Sincronización lista ({conteo} ítems).")
  verificar_alertas()


def bucle_escaneo_periodico():
  primer_escaneo = True
  while True:
    try:
      actualizar_base_de_datos()
      if not primer_escaneo:
        detectar_oportunidades_y_difundir()
      else:
        primer_escaneo = False
    except Exception as e:
      print(f"❌ Error en escaneo: {e}")
    time.sleep(INTERVALO_MINUTOS * 60)


def buscar_item_en_db(query):
  query_clean = query.strip().lower()
  if query_clean in TRADUCCIONES:
    query_clean = TRADUCCIONES[query_clean].lower()

  with db_lock:
    for name in historial_db.keys():
      if name.lower() == query_clean:
        return name
    for name in historial_db.keys():
      if query_clean in name.lower():
        return name
  return None


def generar_reporte_item(item_name):
  with db_lock:
    data = historial_db.get(item_name)
    if not data:
      return "⚠️ No hay registros para este ítem."
    snapshot = {var: list(deq) for var, deq in data.items()}

  msg = f"🐾 <b>REPORTE DE VALORES: {clean_text(item_name.upper())}</b>\n\n"
  variantes_emoji = {
      "REG": "⚪ Normal",
      "FR": "🧪 Fly Ride",
      "NFR": "✨ Neon FR",
      "MFR": "🌈 Mega FR",
  }

  for var_code, label in variantes_emoji.items():
    historial = snapshot.get(var_code, [])
    if not historial:
      continue
    actual = historial[-1]["value"]
    msg += f"<b>{label}</b> ➔ <code>{actual}</code>\n"

    if len(historial) > 1:
      previo = historial[-2]["value"]
      if previo > 0:
        diff = actual - previo
        pct = (diff / previo) * 100
        emoji_var = "🟢" if diff > 0 else ("🔴" if diff < 0 else "⚪")
        msg += (
            f"└ <i>Último cambio (hace 30 min):</i> {emoji_var}"
            f" <b>{pct:+.2f}%</b>\n"
        )
      else:
        msg += "└ <i>Último cambio:</i> ⚪ <b>0.00%</b>\n"

      base_val = historial[0]["value"]
      msg += "└ <b>Historial de cambios:</b>\n"
      for i in range(len(historial) - 1, -1, -1):
        registro = historial[i]
        val = registro["value"]
        pct_base = (
            ((val - base_val) / base_val * 100) if base_val > 0 else 0.0
        )
        pasos_atras = len(historial) - 1 - i
        tiempo_label = (
            "Actual" if pasos_atras == 0 else f"Hace {pasos_atras * 30} min"
        )
        msg += (
            f"   • {tiempo_label} ({registro['timestamp'].split(' - ')[0]}):"
            f" <code>{val}</code> ({pct_base:+.1f}%)\n"
        )
    else:
      msg += "└ <i>Sin historial previo.</i>\n"
    msg += "\n"
  return msg


def generar_top_cambios():
  con_variacion = []
  with db_lock:
    snapshot_db = {
        k: {v: list(deq) for v, deq in val.items()}
        for k, val in historial_db.items()
    }

  for name, data in snapshot_db.items():
    historial = data.get("FR", []) or data.get("REG", [])
    if len(historial) >= 2:
      actual = historial[-1]["value"]
      inicial = historial[0]["value"]
      if inicial > 0:
        diff = actual - inicial
        pct = (diff / inicial) * 100
        con_variacion.append({"name": name, "actual": actual, "pct": pct})

  if not con_variacion:
    return (
        "⏳ <b>Sin historial suficiente.</b> Se necesitan al menos 2 escaneos"
        " acumulados."
    )

  subieron = sorted(
      [x for x in con_variacion if x["pct"] > 0],
      key=lambda x: x["pct"],
      reverse=True,
  )
  bajaron = sorted(
      [x for x in con_variacion if x["pct"] < 0], key=lambda x: x["pct"]
  )

  msg = "📊 <b>TENDENCIAS Y VARIACIONES RECIENTES</b>\n\n🚀 <b>TOP UP:</b>\n"
  for item in subieron[:5]:
    msg += (
        f"• <b>{clean_text(item['name'])}</b>: <code>{item['actual']}</code> (🟢"
        f" <b>+{item['pct']:.2f}%</b>)\n"
    )

  msg += "\n🔻 <b>TOP DOWN:</b>\n"
  for item in bajaron[:5]:
    msg += (
        f"• <b>{clean_text(item['name'])}</b>: <code>{item['actual']}</code> (🔴"
        f" <b>{item['pct']:.2f}%</b>)\n"
    )

  return msg


def comando_buscar(query):
  if not query:
    return "⚠️ Uso correcto: <code>/buscar &lt;texto&gt;</code>"
  query_clean = query.strip().lower()
  coincidencias = []
  with db_lock:
    for name in historial_db.keys():
      if query_clean in name.lower():
        coincidencias.append(name)
  if not coincidencias:
    return f"🔍 Sin resultados para '<b>{clean_text(query)}</b>'."
  msg = f"🔍 <b>RESULTADOS PARA '{clean_text(query.upper())}':</b>\n\n"
  for name in coincidencias[:15]:
    msg += f"• <code>{clean_text(name)}</code>\n"
  return msg


def comando_alerta(chat_id, args_text):
  if not args_text:
    return (
        "⚙️ <b>USO DE /ALERTA</b>\n\n"
        "Sintaxis: <code>/alerta &lt;pet&gt; &lt;variante&gt; &lt;condición&gt;"
        " &lt;valor&gt;</code>\n\n"
        "<b>Ejemplo:</b>\n"
        "<code>/alerta Shadow Dragon FR &gt; 150</code>\n"
        "<code>/alerta Turtle NFR &lt;= 12.5</code>\n\n"
        "<b>Variantes válidas:</b> REG, FR, NFR, MFR\n"
        "<b>Condiciones:</b> &gt;, &lt;, &gt;=, &lt;="
    )

  pattern = re.compile(
      r"^(.*?)\s+(REG|FR|NFR|MFR)\s+(>|<|>=|<=)\s+([0-9]+(?:\.[0-9]+)?)$",
      re.IGNORECASE,
  )
  match = pattern.match(args_text.strip())
  if not match:
    return (
        "⚠️ <b>Formato incorrecto.</b> Ejemplo correcto:\n<code>/alerta Shadow"
        " Dragon FR &gt; 150</code>"
    )

  pet_query, variant, cond, target_val = match.groups()
  variant, target_val = variant.upper(), float(target_val)
  item_encontrado = buscar_item_en_db(pet_query)

  if not item_encontrado:
    return f"❌ Pet no encontrada: '<b>{clean_text(pet_query)}</b>'."

  with db_lock:
    alertas_db.append({
        "chat_id": chat_id,
        "item": item_encontrado,
        "variant": variant,
        "cond": cond,
        "target": target_val,
    })

  return (
      f"✅ <b>Alerta registrada:</b> {clean_text(item_encontrado)}"
      f" ({clean_text(variant)}) {clean_text(cond)} {target_val}"
  )


def comando_mis_alertas(chat_id):
  with db_lock:
    mis_a = [a for a in alertas_db if a["chat_id"] == chat_id]

  if not mis_a:
    return "📭 No tienes alertas activas actualmente."

  msg = "🔔 <b>TUS ALERTAS ACTIVAS:</b>\n\n"
  for i, a in enumerate(mis_a, 1):
    msg += (
        f"{i}. <b>{clean_text(a['item'])}</b> ({clean_text(a['variant'])}) ➔"
        f" <code>{clean_text(a['cond'])} {a['target']}</code>\n"
    )
  return msg


def comando_upgrade(query):
  if not query:
    return (
        "⚠️ Uso correcto: <code>/upgrade &lt;pet&gt; [variante]</code>\nEjemplo:"
        " <code>/upgrade Turtle NFR</code>"
    )

  parts = query.strip().split()
  variante_input = "FR"
  if parts[-1].upper() in ["REG", "FR", "NFR", "MFR"]:
    variante_input = parts[-1].upper()
    pet_query = " ".join(parts[:-1])
  else:
    pet_query = " ".join(parts)

  item_encontrado = buscar_item_en_db(pet_query)
  if not item_encontrado:
    return f"❌ Pet no encontrada: '<b>{clean_text(query)}</b>'."

  with db_lock:
    snapshot_db = {
        k: {v: list(deq) for v, deq in val.items()}
        for k, val in historial_db.items()
    }

  item_data = snapshot_db.get(item_encontrado)
  if (
      not item_data
      or variante_input not in item_data
      or not item_data[variante_input]
  ):
    return (
        f"⚠️ Sin datos disponibles para {clean_text(item_encontrado)}"
        f" ({clean_text(variante_input)})."
    )

  valor_base = item_data[variante_input][-1]["value"]
  if valor_base == 0.0:
    return (
        f"⚠️ <b>{clean_text(item_encontrado)}"
        f" ({clean_text(variante_input)})</b> no tiene valor registrado."
    )

  catalogo = []
  for name, data in snapshot_db.items():
    for var in ["REG", "FR", "NFR", "MFR"]:
      if name == item_encontrado and var == variante_input:
        continue
      h = data.get(var, [])
      val = h[-1]["value"] if h else 0.0
      if val > 0:
        catalogo.append({"nombre": f"{name} ({var})", "val": val})

  upgrades = [x for x in catalogo if x["val"] > valor_base]
  downgrades = [x for x in catalogo if x["val"] < valor_base]

  upgrades.sort(key=lambda x: x["val"])
  downgrades.sort(key=lambda x: x["val"], reverse=True)

  top_up = upgrades[:5]
  top_down = downgrades[:5]

  msg = (
      f"🔄 <b>ANÁLISIS DE TRADE PARA:"
      f" {clean_text(item_encontrado.upper())} ({clean_text(variante_input)})</b>\n"
      f"💵 <b>Valor Base:</b> <code>{valor_base}</code>\n\n"
      "📈 <b>TOP 5 UPGRADES:</b>\n"
  )

  if top_up:
    for item in top_up:
      diff = round(item["val"] - valor_base, 2)
      msg += (
          f"• <b>{clean_text(item['nombre'])}</b> ➔ <code>{item['val']}</code>"
          f" (+{diff})\n"
      )
  else:
    msg += "• No hay ítems superiores disponibles.\n"

  msg += "\n📉 <b>TOP 5 DOWNGRADES:</b>\n"
  if top_down:
    for item in top_down:
      diff = round(valor_base - item["val"], 2)
      msg += (
          f"• <b>{clean_text(item['nombre'])}</b> ➔ <code>{item['val']}</code>"
          f" (-{diff})\n"
      )
  else:
    msg += "• No hay ítems inferiores disponibles.\n"

  return msg


def comando_rango(args_text):
  parts = args_text.strip().split()
  if len(parts) < 2:
    return (
        "⚠️ Uso correcto: <code>/rango &lt;min&gt;"
        " &lt;max&gt;</code>\nEjemplo: <code>/rango 10 20</code>"
    )

  try:
    val_min = float(parts[0])
    val_max = float(parts[1])
  except ValueError:
    return "❌ Los valores deben ser números."

  resultados = []
  with db_lock:
    for name, data in historial_db.items():
      for var in ["REG", "FR", "NFR", "MFR"]:
        h = data.get(var, [])
        if h:
          v = h[-1]["value"]
          if val_min <= v <= val_max:
            resultados.append({"name": f"{name} ({var})", "val": v})

  resultados.sort(key=lambda x: x["val"], reverse=True)

  if not resultados:
    return (
        f"🔍 No se encontraron ítems en el rango de <code>{val_min}</code> a"
        f" <code>{val_max}</code>."
    )

  msg = f"📊 <b>ITEMS EN RANGO DE VALOR ({val_min} - {val_max}):</b>\n\n"
  for item in resultados[:20]:
    msg += f"• <b>{clean_text(item['name'])}</b> ➔ <code>{item['val']}</code>\n"

  if len(resultados) > 20:
    msg += f"\n<i>...y {len(resultados) - 20} ítems más.</i>"

  return msg


def comando_categoria(args_text):
  if not args_text:
    return (
        "⚠️ Uso correcto: <code>/categoria"
        " &lt;Eggs|Pets|Vehicles|Toys|Pet Wear&gt;</code>"
    )

  query = args_text.strip().lower()
  coincidencias = []

  with db_lock:
    for item, cat in categoria_map.items():
      if query in cat.lower() or query in item.lower():
        val_fr = (
            historial_db[item]["FR"][-1]["value"]
            if historial_db[item]["FR"]
            else 0.0
        )
        coincidencias.append({"name": item, "val": val_fr, "cat": cat})

  if not coincidencias:
    return (
        "❌ No se encontraron ítems para la categoría o filtro:"
        f" '<b>{clean_text(args_text)}</b>'."
    )

  coincidencias.sort(key=lambda x: x["val"], reverse=True)

  msg = f"📦 <b>RESULTADOS PARA: {clean_text(args_text.upper())}</b>\n\n"
  for item in coincidencias[:20]:
    msg += (
        f"• <b>{clean_text(item['name'])}</b> (FR): <code>{item['val']}</code>\n"
    )

  return msg


def comando_miinventario(chat_id, args_text):
  if not args_text:
    return (
        "💼 <b>GESTIÓN DE INVENTARIO PERSONAL</b>\n\n"
        "• <code>/miinventario agregar &lt;pet&gt; [variante]</code>\n"
        "• <code>/miinventario remover &lt;pet&gt; [variante]</code>\n"
        "• <code>/miinventario ver</code>\n"
    )

  parts = args_text.strip().split()
  subcmd = parts[0].lower()

  if subcmd == "ver":
    user_inv = inventarios_db.get(chat_id, [])
    if not user_inv:
      return (
          "📭 Tu inventario está vacío. Agrega ítems con <code>/miinventario"
          " agregar &lt;pet&gt;</code>."
      )

    total_actual = 0.0
    msg = "💼 <b>TU INVENTARIO PERSONAL:</b>\n\n"

    with db_lock:
      for i, item in enumerate(user_inv, 1):
        p_name = item["item"]
        var = item["variant"]
        val_act = (
            historial_db[p_name][var][-1]["value"]
            if (p_name in historial_db and historial_db[p_name][var])
            else 0.0
        )
        total_actual += val_act
        msg += (
            f"{i}. <b>{clean_text(p_name)}</b> ({clean_text(var)}) ➔"
            f" <code>{val_act}</code>\n"
        )

    msg += f"\n💰 <b>VALOR TOTAL:</b> <code>{round(total_actual, 2)}</code>"
    return msg

  elif subcmd == "agregar":
    if len(parts) < 2:
      return "⚠️ Especifica la pet a agregar."

    variante = "FR"
    if parts[-1].upper() in ["REG", "FR", "NFR", "MFR"]:
      variante = parts[-1].upper()
      pet_q = " ".join(parts[1:-1])
    else:
      pet_q = " ".join(parts[1:])

    p_found = buscar_item_en_db(pet_q)
    if not p_found:
      return f"❌ Pet no encontrada: '<b>{clean_text(pet_q)}</b>'."

    if chat_id not in inventarios_db:
      inventarios_db[chat_id] = []

    inventarios_db[chat_id].append({"item": p_found, "variant": variante})
    return (
        "✅ Agregado a tu inventario: <b>"
        f"{clean_text(p_found)} ({clean_text(variante)})</b>."
    )

  elif subcmd == "remover":
    if len(parts) < 2:
      return "⚠️ Especifica la pet a remover."

    pet_q = " ".join(parts[1:]).lower()
    user_inv = inventarios_db.get(chat_id, [])

    for item in user_inv:
      if pet_q in item["item"].lower():
        user_inv.remove(item)
        return (
            "🗑️ Removido de tu inventario:"
            f" <b>{clean_text(item['item'])} ({clean_text(item['variant'])})</b>."
        )

    return "❌ Ítem no encontrado en tu inventario."

  return (
      "⚠️ Subcomando inválido. Usa: <code>agregar</code>, <code>remover</code> o"
      " <code>ver</code>."
  )


def comando_grafico(chat_id, query):
  if not query:
    return send_telegram_message(
        chat_id, "⚠️ Uso correcto: <code>/grafico &lt;pet&gt;</code>"
    )

  p_found = buscar_item_en_db(query)
  if not p_found:
    return send_telegram_message(
        chat_id, f"❌ Pet no encontrada: '<b>{clean_text(query)}</b>'."
    )

  with db_lock:
    data = historial_db.get(p_found, {})
    hist_fr = list(data.get("FR", []))

  if not hist_fr:
    return send_telegram_message(
        chat_id, f"⚠️ Sin historial para <b>{clean_text(p_found)}</b>."
    )

  labels = [x["timestamp"].split(" - ")[0] for x in hist_fr]
  values = [x["value"] for x in hist_fr]

  chart_config = {
      "type": "line",
      "data": {
          "labels": labels,
          "datasets": [{
              "label": f"Valor FR - {p_found}",
              "data": values,
              "fill": False,
              "borderColor": "rgb(75, 192, 192)",
              "tension": 0.1,
          }],
      },
  }

  chart_json_str = json.dumps(chart_config)
  encoded_config = urllib.parse.quote(chart_json_str)
  chart_url = f"https://quickchart.io/chart?c={encoded_config}"

  send_telegram_photo(
      chat_id,
      chart_url,
      caption=f"📈 <b>HISTORIAL DE PRECIO: {clean_text(p_found)} (FR)</b>",
  )


def comando_vs(query):
  if not query or "," not in query:
    return (
        "⚠️ Uso correcto: <code>/vs &lt;Pet1&gt; , &lt;Pet2&gt;</code>\nEjemplo:"
        " <code>/vs Shadow Dragon , Frost Dragon</code>"
    )

  parts = query.split(",")
  p1_name = buscar_item_en_db(parts[0])
  p2_name = buscar_item_en_db(parts[1])

  if not p1_name or not p2_name:
    return "❌ Una o ambas pets no fueron encontradas en la base de datos."

  with db_lock:
    d1 = historial_db.get(p1_name, {})
    d2 = historial_db.get(p2_name, {})

  msg = (
      "⚖️ <b>COMPARATIVA DIRECTA</b>\n\n"
      f"🔹 <b>{clean_text(p1_name)}</b> VS 🔸 <b>{clean_text(p2_name)}</b>\n\n"
  )

  for var in ["REG", "FR", "NFR", "MFR"]:
    v1 = d1[var][-1]["value"] if (var in d1 and d1[var]) else 0.0
    v2 = d2[var][-1]["value"] if (var in d2 and d2[var]) else 0.0
    diff = round(v1 - v2, 2)
    signo = "+" if diff > 0 else ""
    msg += (
        f"<b>[{var}]</b>\n"
        f"• {clean_text(p1_name)}: <code>{v1}</code>\n"
        f"• {clean_text(p2_name)}: <code>{v2}</code>\n"
        f"• Dif: <code>{signo}{diff}</code>\n\n"
    )

  return msg


def generar_mensaje_ayuda():
  return (
      "🤖 <b>GUÍA COMPLETA Y COMANDOS DEL BOT</b>\n\n"
      "📌 <b>BÚSQUEDAS Y REPORTES</b>\n"
      "• <code>Escribir nombre</code>: Consulta valores e historial directo (ej:"
      " <code>Bat Dragon</code>).\n"
      "• /buscar <code>&lt;texto&gt;</code>: Busca coincidencias parciales de"
      " nombres.\n"
      "• /top: Muestra las pets con mayores subidas y bajadas.\n"
      "• /vs <code>&lt;Pet1&gt; , &lt;Pet2&gt;</code>: Comparativa directa"
      " entre 2 pets.\n"
      "• /grafico <code>&lt;pet&gt;</code>: Muestra una gráfica de tendencias de"
      " precio.\n\n"
      "📌 <b>FILTROS Y CATEGORÍAS</b>\n"
      "• /rango <code>&lt;min&gt; &lt;max&gt;</code>: Lista ítems dentro de un"
      " rango de valor.\n"
      "• /categoria <code>&lt;Eggs|Pets|Vehicles...&gt;</code>: Lista ítems por"
      " categoría o huevo.\n\n"
      "📌 <b>TRADES Y ESTIMACIONES</b>\n"
      "• /upgrade <code>&lt;pet&gt; [var]</code>: Muestra 5 Upgrades y 5"
      " Downgrades considerando Normal, Neones y Megas.\n\n"
      "📌 <b>ALERTAS DE PRECIO</b>\n"
      "• /alerta <code>&lt;pet&gt; &lt;var&gt; &lt;cond&gt; &lt;valor&gt;</code>:"
      " Configura notificaciones de precio.\n"
      "  <i>Variantes:</i> REG, FR, NFR, MFR | <i>Condiciones:</i> &gt;,"
      " &lt;, &gt;=, &lt;=\n"
      "• /mis_alertas: Muestra tus alertas activas.\n\n"
      "📌 <b>INVENTARIO PERSONAL</b>\n"
      "• /miinventario <code>agregar|remover|ver</code>: Gestiona tu portafolio"
      " y calcula tu valor total en tiempo real."
  )


def procesar_mensajes():
  offset = None
  print("🚀 Bot en línea. Escuchando mensajes...")
  while True:
    try:
      url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
      res = requests.get(
          url, params={"timeout": 10, "offset": offset}, timeout=15
      ).json()

      if res.get("ok") and res.get("result"):
        for update in res["result"]:
          offset = update["update_id"] + 1
          message = update.get("message", {})
          text = message.get("text", "").strip()
          chat_id = message.get("chat", {}).get("id")

          if not text or not chat_id:
            continue

          usuarios_activos.add(chat_id)
          cmd_clean = text.split()[0].lower()

          if cmd_clean in ["/start", "/help"]:
            send_telegram_message(chat_id, generar_mensaje_ayuda())
          elif cmd_clean == "/top":
            send_telegram_message(chat_id, generar_top_cambios())
          elif cmd_clean == "/buscar":
            send_telegram_message(chat_id, comando_buscar(text[7:].strip()))
          elif cmd_clean == "/alerta":
            send_telegram_message(
                chat_id, comando_alerta(chat_id, text[7:].strip())
            )
          elif cmd_clean == "/mis_alertas":
            send_telegram_message(chat_id, comando_mis_alertas(chat_id))
          elif cmd_clean == "/upgrade":
            send_telegram_message(chat_id, comando_upgrade(text[8:].strip()))
          elif cmd_clean == "/rango":
            send_telegram_message(chat_id, comando_rango(text[6:].strip()))
          elif cmd_clean in ["/huevo", "/categoria"]:
            send_telegram_message(
                chat_id, comando_categoria(text[10:].strip())
            )
          elif cmd_clean == "/miinventario":
            send_telegram_message(
                chat_id, comando_miinventario(chat_id, text[13:].strip())
            )
          elif cmd_clean == "/grafico":
            comando_grafico(chat_id, text[8:].strip())
          elif cmd_clean == "/vs":
            send_telegram_message(chat_id, comando_vs(text[3:].strip()))
          elif cargando_datos and len(historial_db) == 0:
            send_telegram_message(
                chat_id,
                "⏳ Cargando base de datos por primera vez... Intenta en 15s.",
            )
          else:
            item_encontrado = buscar_item_en_db(text)
            if item_encontrado:
              send_telegram_message(
                  chat_id, generar_reporte_item(item_encontrado)
              )
            else:
              send_telegram_message(
                  chat_id,
                  f"❌ No encontré la Pet u opción '<b>{clean_text(text)}</b>'."
                  " Usa /help para ver la lista de comandos.",
              )
    except Exception as e:
      print(f"❌ Error procesando actualización: {e}")
      time.sleep(2)


hilo_escaneo = threading.Thread(target=bucle_escaneo_periodico, daemon=True)
hilo_escaneo.start()

procesar_mensajes()
