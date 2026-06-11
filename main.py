from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import sqlite3, hashlib, secrets, time, os
from typing import Optional

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
            time_str   TEXT,
            label      TEXT,
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS tokens (
            token      TEXT PRIMARY KEY,
            created_at INTEGER
        );
    """)
    conn.commit()
    conn.close()
    seed_news()

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
    time: str = ""
    label: str = ""

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
        "INSERT INTO news (id,type,icon,cat,title,desc,time_str,label,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (nid, item.type, item.icon, item.cat, item.title, item.desc, item.time, item.label, int(time.time()))
    )
    conn.commit(); conn.close()
    return {"id": nid}

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

# ── Static ────────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse("index.html")
