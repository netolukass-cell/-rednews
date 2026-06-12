from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import sqlite3, hashlib, secrets, time, os
from typing import Optional
import httpx

from fastapi.staticfiles import StaticFiles

app = FastAPI(docs_url=None, redoc_url=None)

DB_PATH = os.environ.get("DB_PATH", "rednews.db")
TOKEN_TTL = 86400  # 24h

# ── DB ────────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS news (
            id         TEXT PRIMARY KEY,
            type       TEXT DEFAULT 'item',
            icon       TEXT,
            cat        TEXT,
            title      TEXT,
            desc       TEXT,
            body       TEXT DEFAULT '',
            image_url  TEXT DEFAULT '',
            time_str   TEXT,
            label      TEXT,
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS tokens (
            token      TEXT PRIMARY KEY,
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS comments (
            id         TEXT PRIMARY KEY,
            article_id TEXT NOT NULL,
            author     TEXT NOT NULL,
            body       TEXT NOT NULL,
            likes      INTEGER DEFAULT 0,
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS sponsors (
            slot       TEXT PRIMARY KEY,
            name       TEXT,
            tagline    TEXT,
            cta_text   TEXT,
            cta_url    TEXT,
            image_url  TEXT,
            theme      TEXT DEFAULT 'dark'
        );
    """)
    # migrate: add columns if missing (safe on existing DB)
    for col, definition in [("body","TEXT DEFAULT ''"), ("image_url","TEXT DEFAULT ''")]:
        try:
            conn.execute(f"ALTER TABLE news ADD COLUMN {col} {definition}")
            conn.commit()
        except Exception:
            pass
    conn.commit()
    conn.close()
    seed_news()
    seed_sponsors()
    seed_solevan_article()

DEFAULT_NEWS = [
    ("d1","featured","🚔","Segurança Pública",
     "Sheriff persegue suspeito por 40 minutos — sem conseguir alcançar",
     "Viatura foi vista em velocidade máxima de 60km/h enquanto suspeito fugia a pé pelo deserto.",
     "Hoje, 14:32 · Red County Sheriff's Dept.","EXCLUSIVO"),
    ("d2","featured","💥","Policial",
     'Terceiro "acidente" este mês no posto da Route 68 levanta suspeitas',
     'Moradores pedem sinalização. Autoridades culpam "o asfalto úmido" — mesmo em dia de sol.',
     "Hoje, 11:08 · Route 68, Red County","URGENTE"),
    ("d3","item","🏦","Economia",
     'Blaine County Savings nega estar seco: "tivemos apenas uma reorganização de caixa"',
     "","Hoje, 09:15",""),
    ("d4","item","🌵","Interior",
     "Fazendeiro de Palomino Creek oferece R$500 por informações sobre suas próprias vacas",
     "","Ontem, 18:44",""),
    ("d5","item","🔫","Segurança",
     'Loja de armas de Dillimore registra recorde de vendas — "clientela muito motivada este mês"',
     "","Ontem, 15:20",""),
    ("d6","item","🚗","Trânsito",
     "Corrida não-oficial na Route 1 termina com todos os carros no fosso — exceto o vencedor",
     "","Ontem, 22:10",""),
]

def seed_news():
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
    if count == 0:
        t = int(time.time())
        for d in DEFAULT_NEWS:
            conn.execute(
                "INSERT OR IGNORE INTO news (id,type,icon,cat,title,desc,time_str,label,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (*d, t)
            )
        conn.commit()
    conn.close()

DEFAULT_SPONSORS = [
    ("hero", "Bar do Joe", "Onde Red County se encontra", "Conheça o Bar do Joe", "#", "assets/spon-bardojoe.png", "dark"),
    ("sidebar", "Well Stacked Pizza", "A fatia mais alta de Red County", "Ver cardápio", "#", "assets/spon-pizza.png", "light"),
]

def seed_sponsors():
    conn = get_db()
    for s in DEFAULT_SPONSORS:
        conn.execute(
            "INSERT OR IGNORE INTO sponsors (slot,name,tagline,cta_text,cta_url,image_url,theme) VALUES (?,?,?,?,?,?,?)",
            s
        )
    conn.commit()
    conn.close()

SOLEVAN_BODY = """
<div style="text-align:center;margin-bottom:24px">
  <img src="https://i.imgur.com/mc4iVWI.png" alt="Campeonato de Sinuca" style="max-width:100%;border-radius:8px">
</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:28px;align-items:start;margin-bottom:28px">
  <div style="text-align:center">
    <img src="https://i.imgur.com/B2O7GeZ.png" alt="Jack Solevan" style="width:100%;max-width:360px;border-radius:8px">
    <p style="color:#888;font-style:italic;font-size:13px;margin-top:8px">Jack Solevan ergue o cheque de US$ 10.000 momentos após cravar a bola 8 que decidiu o título.</p>
  </div>
  <div>
    <p><strong style="color:#b30000">MONTGOMERY, RED COUNTY</strong> — Foram quase três horas de taco, giz e silêncio tenso entre uma tacada e outra, mas no fim sobrou um nome só: <strong style="color:#b30000">Jack Solevan</strong>, que embolsou <strong>US$ 10.000</strong> ao vencer o Campeonato de Sinuca do <strong>Bar do Joe</strong> na noite desta terça.</p>
    <p>A casa encheu cedo. Quando o balcão fechou as inscrições, a chave já tinha gente de sobra disputando as mesas — e plateia o bastante pra deixar qualquer iniciante com a mão tremendo no taco.</p>
    <p>Solevan não foi o favorito declarado. Subiu rodada por rodada, segurou pressão na semifinal e chegou à decisão sem dar muito espetáculo, mas sem errar o que não podia errar. Foi exatamente o que bastou.</p>
  </div>
</div>
<hr style="border:none;border-top:1px solid #2a2a2e;margin:24px 0">
<table style="width:100%;border-collapse:collapse;text-align:center;margin-bottom:28px">
  <tr>
    <td style="padding:14px;border:1px solid #1d1d22"><strong style="color:#b30000;display:block;font-size:11px;letter-spacing:1px;font-family:monospace;margin-bottom:4px">CAMPEÃO</strong><strong>Jack Solevan</strong></td>
    <td style="padding:14px;border:1px solid #1d1d22"><strong style="color:#b30000;display:block;font-size:11px;letter-spacing:1px;font-family:monospace;margin-bottom:4px">PRÊMIO</strong><strong>US$ 10.000</strong></td>
    <td style="padding:14px;border:1px solid #1d1d22"><strong style="color:#b30000;display:block;font-size:11px;letter-spacing:1px;font-family:monospace;margin-bottom:4px">LOCAL</strong><strong>Bar do Joe</strong></td>
    <td style="padding:14px;border:1px solid #1d1d22"><strong style="color:#b30000;display:block;font-size:11px;letter-spacing:1px;font-family:monospace;margin-bottom:4px">EVENTO</strong><strong>Campeonato de Sinuca</strong></td>
  </tr>
</table>
<hr style="border:none;border-top:1px solid #2a2a2e;margin:24px 0">
<h2>A FINAL QUE PAROU O BAR</h2>
<p>A decisão colocou frente a frente <strong>Jack Solevan</strong> e <strong>Klaus Vogel</strong>. Vogel abriu vantagem, encaçapou bem no começo e chegou a deixar Solevan na corda bamba. Mas bastou uma bola fácil escapar da caçapa pra virada começar.</p>
<p>Daí pra frente foi Solevan no controle. Tacada limpa, sem firula, fechando a mesa com a calma de quem já sabia onde ia terminar. A bola 8 caiu na lateral direita e o bar veio abaixo. <strong>Lee Nash</strong>, que tinha caído na semi, foi um dos primeiros a aplaudir.</p>
<p><strong>Riley Vance</strong>, <strong>Tremaine Hill</strong> e <strong>Uriell Garret</strong> também passaram pelas mesas e ajudaram a fazer a noite render. Mas o cheque, esse, saiu com um dono só.</p>
<blockquote style="border-left:3px solid #b30000;padding-left:16px;margin:20px 0;color:#ccc;font-style:italic">
  <p>"No meio da final eu já tava perdendo. Aí o Vogel deixou uma boba escapar e eu pensei: agora é minha. Dez mil dólares mudam a semana de qualquer um."</p>
  <footer style="color:#b30000;font-style:normal;font-weight:700;margin-top:8px">— Jack Solevan, campeão</footer>
</blockquote>
<hr style="border:none;border-top:1px solid #2a2a2e;margin:24px 0">
<h2 style="color:#b30000">BAR DO JOE: ONDE MONTGOMERY SE ENCONTRA</h2>
<p>Mais uma vez o <strong>Bar do Joe</strong> provou que, quando chama, a cidade aparece. Mesa cheia, cerveja liberada e aquela mistura de quem joga pra valer com quem só veio comentar tacada alheia.</p>
<p>E a julgar pelo movimento de ontem, essa não vai ser a última. A organização já dava como certa uma nova edição, com a bolada do prêmio podendo subir ainda mais.</p>
<p>Fica o aviso da <strong style="color:#b30000">Red News</strong>: na próxima, chegue antes de o balcão fechar as inscrições. As boas histórias de Red County não esperam quem fica em casa.</p>
<hr style="border:none;border-top:1px solid #2a2a2e;margin:24px 0">
<div style="text-align:right;color:#888;font-size:13px">
  <em>Publicado por</em><br>
  <strong style="color:#b30000;font-size:15px">Beau Hollister</strong><br>
  <strong>Red News</strong> — Rádio · Jornal · Red County
</div>
"""

def seed_solevan_article():
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO news (id,type,icon,cat,title,desc,body,image_url,time_str,label,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("solevan-2026-06-11", "featured", "🎱", "Esportes",
         "Solevan fatura US$ 10 mil e vira o novo rei da sinuca",
         "Final apertada no Bar do Joe coroa Jack Solevan diante de casa lotada em Montgomery",
         SOLEVAN_BODY,
         "https://i.imgur.com/mc4iVWI.png",
         "Hoje, 11/06", "EXCLUSIVO",
         int(time.time()))
    )
    conn.commit()
    conn.close()

init_db()

# ── Auth helper ───────────────────────────────────────────────────────────────

def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Não autorizado")
    token = authorization[7:]
    conn = get_db()
    row = conn.execute("SELECT created_at FROM tokens WHERE token=?", (token,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(401, "Token inválido")
    if time.time() - row["created_at"] > TOKEN_TTL:
        conn = get_db()
        conn.execute("DELETE FROM tokens WHERE token=?", (token,))
        conn.commit(); conn.close()
        raise HTTPException(401, "Sessão expirada")
    return token

def new_token():
    token = secrets.token_hex(32)
    conn = get_db()
    conn.execute("INSERT INTO tokens (token,created_at) VALUES (?,?)", (token, int(time.time())))
    conn.commit(); conn.close()
    return token

# ── Models ────────────────────────────────────────────────────────────────────

class SetupReq(BaseModel):
    password: str

class LoginReq(BaseModel):
    password: str

class ChangePwdReq(BaseModel):
    current_password: str
    new_password: str

class NewsItem(BaseModel):
    type: str = "item"
    icon: str = "📰"
    cat: str
    title: str
    desc: str = ""
    body: str = ""
    image_url: str = ""
    time: str = ""
    label: str = ""

class NewsEdit(BaseModel):
    type: Optional[str] = None
    cat: Optional[str] = None
    title: Optional[str] = None
    desc: Optional[str] = None
    body: Optional[str] = None
    image_url: Optional[str] = None
    time_str: Optional[str] = None
    label: Optional[str] = None

class StreamUpdate(BaseModel):
    url: Optional[str] = None
    is_live: Optional[bool] = None

# ── Auth endpoints ────────────────────────────────────────────────────────────

@app.get("/api/auth/status")
def auth_status():
    conn = get_db()
    has = bool(conn.execute("SELECT 1 FROM settings WHERE key='admin_hash'").fetchone())
    conn.close()
    return {"has_password": has}

@app.post("/api/auth/setup")
def setup_password(req: SetupReq):
    conn = get_db()
    if conn.execute("SELECT 1 FROM settings WHERE key='admin_hash'").fetchone():
        conn.close()
        raise HTTPException(400, "Senha já configurada")
    if len(req.password) < 6:
        conn.close()
        raise HTTPException(400, "Mínimo 6 caracteres")
    h = hashlib.sha256(req.password.encode()).hexdigest()
    conn.execute("INSERT INTO settings (key,value) VALUES ('admin_hash',?)", (h,))
    conn.commit(); conn.close()
    return {"token": new_token()}

@app.post("/api/auth/login")
def login(req: LoginReq):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key='admin_hash'").fetchone()
    conn.close()
    if not row:
        raise HTTPException(400, "Nenhuma senha configurada")
    if hashlib.sha256(req.password.encode()).hexdigest() != row["value"]:
        raise HTTPException(401, "Senha incorreta")
    return {"token": new_token()}

@app.post("/api/auth/logout")
def logout(token: str = Depends(verify_token)):
    conn = get_db()
    conn.execute("DELETE FROM tokens WHERE token=?", (token,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/api/auth/change")
def change_password(req: ChangePwdReq, token: str = Depends(verify_token)):
    if len(req.new_password) < 6:
        raise HTTPException(400, "Mínimo 6 caracteres")
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key='admin_hash'").fetchone()
    if hashlib.sha256(req.current_password.encode()).hexdigest() != row["value"]:
        conn.close()
        raise HTTPException(401, "Senha atual incorreta")
    h = hashlib.sha256(req.new_password.encode()).hexdigest()
    conn.execute("UPDATE settings SET value=? WHERE key='admin_hash'", (h,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/api/auth/reset")
def factory_reset(token: str = Depends(verify_token)):
    conn = get_db()
    conn.executescript("DELETE FROM settings; DELETE FROM news; DELETE FROM tokens;")
    conn.commit(); conn.close()
    seed_news()
    return {"ok": True}

# ── News endpoints ────────────────────────────────────────────────────────────

@app.get("/api/news")
def get_news():
    conn = get_db()
    rows = conn.execute("SELECT * FROM news ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/news")
def add_news(item: NewsItem, token: str = Depends(verify_token)):
    nid = secrets.token_hex(8)
    conn = get_db()
    conn.execute(
        "INSERT INTO news (id,type,icon,cat,title,desc,body,image_url,time_str,label,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (nid, item.type, item.icon, item.cat, item.title, item.desc, item.body, item.image_url, item.time, item.label, int(time.time()))
    )
    conn.commit(); conn.close()
    return {"id": nid}

@app.put("/api/news/{news_id}")
def edit_news(news_id: str, data: NewsEdit, token: str = Depends(verify_token)):
    conn = get_db()
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE news SET {sets} WHERE id=?", (*fields.values(), news_id))
        conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/api/news/{news_id}")
def delete_news(news_id: str, token: str = Depends(verify_token)):
    conn = get_db()
    conn.execute("DELETE FROM news WHERE id=?", (news_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/api/news/reset")
def reset_news(token: str = Depends(verify_token)):
    conn = get_db()
    conn.execute("DELETE FROM news")
    conn.commit(); conn.close()
    seed_news()
    return {"ok": True}

# ── Stream endpoints ──────────────────────────────────────────────────────────

@app.get("/api/stream")
def get_stream():
    conn = get_db()
    url_row  = conn.execute("SELECT value FROM settings WHERE key='stream_url'").fetchone()
    live_row = conn.execute("SELECT value FROM settings WHERE key='is_live'").fetchone()
    conn.close()
    return {
        "url":     url_row["value"]  if url_row  else "",
        "is_live": live_row["value"] == "1" if live_row else False,
    }

@app.put("/api/stream")
def update_stream(data: StreamUpdate, token: str = Depends(verify_token)):
    conn = get_db()
    if data.url is not None:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('stream_url',?)", (data.url,))
    if data.is_live is not None:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('is_live',?)",
                     ("1" if data.is_live else "0",))
    conn.commit(); conn.close()
    return {"ok": True}

# ── Weather & Rates ───────────────────────────────────────────────────────────

_weather_cache = {"data": None, "ts": 0}
_rates_cache   = {"data": None, "ts": 0}
CACHE_TTL = 600  # 10 min

WMO_DESC = {
    0:"Céu limpo", 1:"Predominantemente limpo", 2:"Parcialmente nublado",
    3:"Nublado", 45:"Neblina", 48:"Neblina com gelo",
    51:"Chuvisco leve", 53:"Chuvisco moderado", 55:"Chuvisco intenso",
    61:"Chuva leve", 63:"Chuva moderada", 65:"Chuva forte",
    71:"Neve leve", 73:"Neve moderada", 75:"Neve forte",
    80:"Pancadas de chuva", 81:"Pancadas moderadas", 82:"Pancadas fortes",
    95:"Tempestade", 96:"Tempestade c/ granizo", 99:"Tempestade forte",
}

def wmo_icon(code):
    if code in (0, 1):         return "☀️"
    if code in (2, 3):         return "⛅"
    if code in (45, 48):       return "🌫️"
    if 51 <= code <= 55:       return "🌦️"
    if 61 <= code <= 65:       return "🌧️"
    if 71 <= code <= 75:       return "❄️"
    if 80 <= code <= 82:       return "🌧️"
    if code >= 95:             return "⛈️"
    return "🌡️"

def road_condition(code, wind):
    if code >= 95:  return "⛔", "Risco alto — evite sair"
    if code >= 80:  return "🔴", "Pista alagada — cuidado"
    if code >= 61:  return "🟡", "Pista molhada"
    if code in (45, 48): return "🟠", "Visibilidade reduzida"
    if wind > 50:   return "🟡", "Vento forte"
    return "🟢", "Pista seca — normal"

@app.get("/api/weather")
async def get_weather():
    now = time.time()
    if _weather_cache["data"] and now - _weather_cache["ts"] < CACHE_TTL:
        return _weather_cache["data"]
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": 35.37, "longitude": -119.02,
                    "current": "temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m",
                    "timezone": "America/Los_Angeles",
                }
            )
            raw = r.json()
        c    = raw["current"]
        code = c["weather_code"]
        wind = c["wind_speed_10m"]
        rd_icon, rd_text = road_condition(code, wind)
        data = {
            "temp":        round(c["temperature_2m"]),
            "humidity":    c["relative_humidity_2m"],
            "wind":        round(wind),
            "code":        code,
            "description": WMO_DESC.get(code, "—"),
            "icon":        wmo_icon(code),
            "road_icon":   rd_icon,
            "road_text":   rd_text,
        }
        _weather_cache["data"] = data
        _weather_cache["ts"]   = now
        return data
    except Exception:
        return {"temp":"—","humidity":"—","wind":"—","code":0,
                "description":"Sem dados","icon":"🌡️","road_icon":"⚫","road_text":"Sem dados"}

@app.get("/api/rates")
async def get_rates():
    now = time.time()
    if _rates_cache["data"] and now - _rates_cache["ts"] < CACHE_TTL:
        return _rates_cache["data"]
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get("https://economia.awesomeapi.com.br/json/last/USD-BRL,EUR-BRL")
            raw = r.json()
        usd = raw["USDBRL"]
        eur = raw["EURBRL"]
        data = {
            "usd": {"rate": float(usd["bid"]), "change": float(usd["pctChange"])},
            "eur": {"rate": float(eur["bid"]), "change": float(eur["pctChange"])},
        }
        _rates_cache["data"] = data
        _rates_cache["ts"]   = now
        return data
    except Exception:
        return {"usd":{"rate":0,"change":0},"eur":{"rate":0,"change":0}}

# ── Ticker endpoint ───────────────────────────────────────────────────────────

class TickerUpdate(BaseModel):
    text: Optional[str] = None
    use_custom: Optional[bool] = None

@app.get("/api/ticker")
def get_ticker():
    conn = get_db()
    text_row = conn.execute("SELECT value FROM settings WHERE key='ticker_text'").fetchone()
    custom_row = conn.execute("SELECT value FROM settings WHERE key='ticker_custom'").fetchone()
    conn.close()
    return {
        "text": text_row["value"] if text_row else "",
        "use_custom": (custom_row["value"] == "1") if custom_row else False,
    }

@app.put("/api/ticker")
def update_ticker(data: TickerUpdate, token: str = Depends(verify_token)):
    conn = get_db()
    if data.text is not None:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('ticker_text',?)", (data.text,))
    if data.use_custom is not None:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('ticker_custom',?)",
                     ("1" if data.use_custom else "0",))
    conn.commit(); conn.close()
    return {"ok": True}

# ── Comments endpoints ────────────────────────────────────────────────────────

class CommentItem(BaseModel):
    author: str
    body: str

@app.get("/api/comments/{article_id}")
def get_comments(article_id: str):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM comments WHERE article_id=? ORDER BY created_at DESC", (article_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/comments/{article_id}")
def add_comment(article_id: str, item: CommentItem):
    if not item.author.strip() or not item.body.strip():
        raise HTTPException(400, "Nome e comentário obrigatórios")
    cid = secrets.token_hex(8)
    conn = get_db()
    conn.execute(
        "INSERT INTO comments (id,article_id,author,body,likes,created_at) VALUES (?,?,?,?,0,?)",
        (cid, article_id, item.author.strip()[:80], item.body.strip()[:2000], int(time.time()))
    )
    conn.commit()
    conn.close()
    return {"id": cid}

@app.post("/api/comments/{article_id}/{comment_id}/like")
def like_comment(article_id: str, comment_id: str):
    conn = get_db()
    conn.execute(
        "UPDATE comments SET likes=likes+1 WHERE id=? AND article_id=?", (comment_id, article_id)
    )
    conn.commit()
    conn.close()
    return {"ok": True}

# ── Sponsors endpoints ────────────────────────────────────────────────────────

class SponsorUpdate(BaseModel):
    name: Optional[str] = None
    tagline: Optional[str] = None
    cta_text: Optional[str] = None
    cta_url: Optional[str] = None
    image_url: Optional[str] = None
    theme: Optional[str] = None

@app.get("/api/sponsors")
def get_sponsors():
    conn = get_db()
    rows = conn.execute("SELECT * FROM sponsors").fetchall()
    conn.close()
    return {r["slot"]: dict(r) for r in rows}

@app.put("/api/sponsors/{slot}")
def update_sponsor(slot: str, data: SponsorUpdate, token: str = Depends(verify_token)):
    conn = get_db()
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE sponsors SET {sets} WHERE slot=?", (*fields.values(), slot))
        conn.commit()
    conn.close()
    return {"ok": True}

# ── Static ────────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse("index.html")

app.mount("/assets", StaticFiles(directory="assets"), name="assets")
