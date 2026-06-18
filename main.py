from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
import psycopg2, psycopg2.extras, hashlib, secrets, time, os, base64
import sqlite3
from typing import Optional
import httpx

from fastapi.staticfiles import StaticFiles

app = FastAPI(docs_url=None, redoc_url=None)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
TOKEN_TTL = 86400  # 24h
SQLITE_PATH = os.environ.get("SQLITE_PATH", "rednews.local.db")
ADMIN_ENABLED = os.environ.get("ADMIN_ENABLED", "").lower() in {"1", "true", "yes"}
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")
DEFAULT_STREAM_URL = os.environ.get("DEFAULT_STREAM_URL", "http://207.58.172.237:8000/rednews.mp3")
PERSISTENT_COMMENTS_URL = os.environ.get("PERSISTENT_COMMENTS_URL", "https://rednews-1.onrender.com").rstrip("/")
PERSISTENT_COMMENTS_TIMEOUT = float(os.environ.get("PERSISTENT_COMMENTS_TIMEOUT", "75"))

# ── DB ────────────────────────────────────────────────────────────────────────

def get_db():
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def db_backend():
    return "postgres" if DATABASE_URL else "sqlite"

def ensure_comment_parent_id(cur):
    if DATABASE_URL:
        db_execute(cur, "ALTER TABLE comments ADD COLUMN IF NOT EXISTS parent_id TEXT")
        return
    db_execute(cur, "PRAGMA table_info(comments)")
    cols = {r["name"] for r in cur.fetchall()}
    if "parent_id" not in cols:
        db_execute(cur, "ALTER TABLE comments ADD COLUMN parent_id TEXT")

def should_proxy_comments():
    return not DATABASE_URL and bool(os.environ.get("RENDER")) and bool(PERSISTENT_COMMENTS_URL)

def proxy_comment_request(method: str, path: str, payload=None):
    try:
        timeout = httpx.Timeout(PERSISTENT_COMMENTS_TIMEOUT, connect=20)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.request(method, f"{PERSISTENT_COMMENTS_URL}{path}", json=payload)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Falha ao acessar comentarios persistentes: {exc}") from exc

def db_execute(cur, query, params=()):
    if not DATABASE_URL:
        query = query.replace("%s", "?")
    return cur.execute(query, params)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    db_execute(cur, """
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    db_execute(cur, """
        CREATE TABLE IF NOT EXISTS news (
            id         TEXT PRIMARY KEY,
            type       TEXT DEFAULT 'item',
            icon       TEXT,
            cat        TEXT,
            title      TEXT,
            "desc"     TEXT,
            body       TEXT DEFAULT '',
            image_url  TEXT DEFAULT '',
            time_str   TEXT,
            label      TEXT,
            created_at BIGINT
        )
    """)
    db_execute(cur, """
        CREATE TABLE IF NOT EXISTS tokens (
            token      TEXT PRIMARY KEY,
            created_at BIGINT
        )
    """)
    db_execute(cur, """
        CREATE TABLE IF NOT EXISTS comments (
            id         TEXT PRIMARY KEY,
            article_id TEXT NOT NULL,
            parent_id  TEXT,
            author     TEXT NOT NULL,
            body       TEXT NOT NULL,
            likes      INTEGER DEFAULT 0,
            created_at BIGINT
        )
    """)
    ensure_comment_parent_id(cur)
    db_execute(cur, """
        CREATE TABLE IF NOT EXISTS sponsors (
            slot      TEXT PRIMARY KEY,
            name      TEXT,
            tagline   TEXT,
            cta_text  TEXT,
            cta_url   TEXT,
            image_url TEXT,
            theme     TEXT DEFAULT 'dark'
        )
    """)
    conn.commit()
    cur.close(); conn.close()
    seed_news()
    seed_sponsors()
    seed_solevan_article()
    seed_montgomery_helmet_article()
    seed_cleavon_article()
    seed_silencio_distintivo_cronica()
    seed_bar_do_joe_attack_article()
    seed_montgore_article()
    seed_montgore_comments()

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
    conn = get_db(); cur = conn.cursor()
    db_execute(cur, "SELECT COUNT(*) AS count FROM news")
    if cur.fetchone()["count"] == 0:
        t = int(time.time())
        for d in DEFAULT_NEWS:
            db_execute(cur,
                'INSERT INTO news (id,type,icon,cat,title,"desc",time_str,label,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING',
                (*d, t)
            )
    conn.commit(); cur.close(); conn.close()

DEFAULT_SPONSORS = [
    ("hero", "Bar do Joe", "Onde Red County se encontra", "Conheça o Bar do Joe", "#", "assets/spon-bardojoe.png", "dark"),
    ("sidebar", "Well Stacked Pizza", "A fatia mais alta de Red County", "Ver cardápio", "#", "assets/spon-pizza.png", "light"),
]

def seed_sponsors():
    conn = get_db(); cur = conn.cursor()
    for s in DEFAULT_SPONSORS:
        db_execute(cur,
            "INSERT INTO sponsors (slot,name,tagline,cta_text,cta_url,image_url,theme) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (slot) DO NOTHING",
            s
        )
    conn.commit(); cur.close(); conn.close()

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
    conn = get_db(); cur = conn.cursor()
    db_execute(cur,
        'INSERT INTO news (id,type,icon,cat,title,"desc",body,image_url,time_str,label,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET type=EXCLUDED.type,icon=EXCLUDED.icon,cat=EXCLUDED.cat,title=EXCLUDED.title,"desc"=EXCLUDED."desc",body=EXCLUDED.body,image_url=EXCLUDED.image_url,time_str=EXCLUDED.time_str,label=EXCLUDED.label',
        ("solevan-2026-06-11", "item", "🎱", "Esportes",
         "Solevan fatura US$ 10 mil e vira o novo rei da sinuca",
         "Final apertada no Bar do Joe coroa Jack Solevan diante de casa lotada em Montgomery",
         SOLEVAN_BODY, "https://i.imgur.com/mc4iVWI.png",
         "Hoje, 11/06", "EXCLUSIVO", int(time.time()))
    )
    conn.commit(); cur.close(); conn.close()

CLEAVON_BODY = """
<p><strong style="color:#cc0000">Era para ser uma noite comum em Red County. Não foi.</strong> Um carro parado no meio da via, farol aceso, motor ligado — e, ao volante, um homem completamente apagado. A cena travou o trânsito, juntou curiosos e terminou com uma pergunta que a cidade inteira repete até agora: como é que <strong style="color:#cc0000">esse</strong> motorista foi parar em casa por conta própria?</p>
<p>O nome dele é <strong style="color:#cc0000">Cleavon Mclister</strong>. Guarde, porque essa coluna vai repetir algumas vezes.</p>
<figure style="margin:28px 0">
  <img src="https://i.imgur.com/INNWjyD.png" alt="Cleavon Mclister durante abordagem" style="width:100%;border-radius:8px">
  <figcaption style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#777;line-height:1.5;margin-top:10px">Mclister sentado na porta do veículo durante a abordagem. Sobre o porta-malas, copos e petiscos largados — detalhe que ninguém deixou passar.</figcaption>
</figure>
<h2><strong style="color:#cc0000">O FLAGRA</strong></h2>
<p>Segundo testemunhas, o veículo estava <strong style="color:#cc0000">atravessado na pista</strong>, obstruindo a passagem, enquanto o condutor seguia tranquilo no mundo dos sonhos. Houve buzina. Houve gente batendo no vidro. Houve até quem sacasse o celular para registrar. E o motorista? Nada. Só acordou quando a cena já tinha virado espetáculo público.</p>
<p>Quando a viatura chegou, o roteiro era de manual: carro mal posicionado, motorista desorientado e, sobre o porta-malas, <strong style="color:#cc0000">copos e restos de comida</strong> que, convenhamos, não combinam muito com a versão de "só um cochilo".</p>
<h2><strong style="color:#cc0000">A SUSPEITA QUE NÃO SAIU DO AR</strong></h2>
<p>A palavra "embriaguez" pairou sobre a abordagem do início ao fim. E faz sentido: quem dorme no meio do trânsito, com o carro ligado e a noite ainda jovem, raramente está apenas "indisposto". Dormiu de cansaço, ou <strong style="color:#cc0000">passou do ponto na bebida</strong>?</p>
<blockquote>
  <p>"Eu só tinha cochilado. Tava cansado, juro. Não bebi nada demais."</p>
  <div class="bq-author">Cleavon Mclister, ao ser abordado</div>
</blockquote>
<p>"Nada demais." Anote essa também. Porque entre o "nada demais" dele e o carro plantado no meio da via, sobra um buraco enorme nessa história.</p>
<figure style="margin:28px 0">
  <img src="https://i.imgur.com/Z11FovM.png" alt="Operação policial no cruzamento da Inside Track" style="width:100%;border-radius:8px">
  <figcaption style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#777;line-height:1.5;margin-top:10px">Operação montada no cruzamento da Inside Track: cones, viatura da SFPD e reforço policial para conter a movimentação.</figcaption>
</figure>
<h2><strong style="color:#cc0000">A LIBERAÇÃO QUE NINGUÉM ENTENDEU</strong></h2>
<p>Aqui a coluna ergue a sobrancelha. Depois de toda a novela — carro parado, motorista apagado, suspeita escancarada e operação montada com cones e viatura —, o desfecho foi um só: <strong style="color:#cc0000">Mclister foi liberado</strong>. E saiu andando, como quem tinha apenas parado para amarrar o sapato.</p>
<p>Faltou bafômetro? Faltou rigor? Ou alguém tem amigo nos lugares certos? A <strong style="color:#cc0000">Red News</strong> não vai deixar essa passar batido — e promete voltar ao assunto.</p>
<div class="resumo">
  <div class="resumo-ttl">Entenda o caso</div>
  <div class="resumo-item"><span class="rdot"></span><span>Cleavon Mclister apagou ao volante no meio da via.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>A suspeita de embriaguez acompanhou toda a abordagem.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>Uma operação foi montada no local, com cones e viaturas.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>Mesmo assim, ele foi liberado minutos depois.</span></div>
</div>
"""

def seed_cleavon_article():
    conn = get_db(); cur = conn.cursor()
    db_execute(cur,
        'INSERT INTO news (id,type,icon,cat,title,"desc",body,image_url,time_str,label,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET type=EXCLUDED.type,icon=EXCLUDED.icon,cat=EXCLUDED.cat,title=EXCLUDED.title,"desc"=EXCLUDED."desc",body=EXCLUDED.body,image_url=EXCLUDED.image_url,time_str=EXCLUDED.time_str,label=EXCLUDED.label,created_at=EXCLUDED.created_at',
        ("cleavon-mclister-2026-06-15", "item", "🚨", "Policial",
         "Dormiu no volante no meio da rua — e saiu andando",
         "Cleavon Mclister apagou no meio da via, virou espetáculo público e acabou liberado minutos depois.",
         CLEAVON_BODY, "https://i.imgur.com/INNWjyD.png",
         "Hoje, 15/06", "EXCLUSIVO", int(time.time()) + 10)
    )
    conn.commit(); cur.close(); conn.close()

MONTGOMERY_HELMET_BODY = """
<p><strong style="color:#cc0000">Montgomery acordou com uma pergunta atravessada na garganta:</strong> desde quando ficar parado ao lado de uma moto vira caso de multa por capacete?</p>
<p>Um <strong style="color:#cc0000">homem ainda não identificado</strong> foi abordado por um sheriff durante uma patrulha noturna e acabou multado por falta de capacete. O detalhe que incendiou a conversa nas calçadas é simples: segundo quem viu a cena, ele <strong style="color:#cc0000">não estava pilotando</strong>. Estava parado.</p>
<figure style="margin:28px 0">
  <img src="assets/montgomery-capacete.jpg" alt="Homem abordado ao lado de uma moto em Montgomery" style="width:100%;border-radius:8px">
  <figcaption style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#777;line-height:1.5;margin-top:10px">Abordagem em Montgomery: moto parada, viatura na via e um sheriff conduzindo a conversa que terminou em multa.</figcaption>
</figure>
<h2><strong style="color:#cc0000">PARADO, MAS MULTADO</strong></h2>
<p>A cena parece pequena, mas em Red County nada fica pequeno por muito tempo. A moto estava encostada, o homem conversava com o oficial e, minutos depois, veio a notícia que correu mais rápido que sirene: <strong style="color:#cc0000">multa por falta de capacete</strong>.</p>
<p>É claro que a segurança no trânsito importa. Mas a pergunta que ficou martelando é outra: se o condutor estava parado, por que a caneta pesou tanto?</p>
<blockquote>
  <p>"O cara nem saiu com a moto. Parecia mais que estavam procurando motivo."</p>
  <div class="bq-author">Testemunha que acompanhou a abordagem</div>
</blockquote>
<h2><strong style="color:#cc0000">RIGOR OU RECADO?</strong></h2>
<p>Nos últimos dias, moradores de Montgomery vêm comentando um aumento nas abordagens. Carro parado, moto encostada, gente reunida na esquina: tudo parece motivo para pergunta, documento e aquela olhada demorada que ninguém sabe se é rotina ou recado.</p>
<p>A versão oficial ainda não veio, mas a rua já montou a própria teoria: os sheriffs podem estar apertando o cerco atrás de algo maior. <strong style="color:#cc0000">Estão procurando alguém? Uma rota? Um padrão?</strong> Ou Montgomery virou laboratório de tolerância zero?</p>
<h2><strong style="color:#cc0000">O QUE ELES ESTÃO PROCURANDO?</strong></h2>
<p>É aí que a história cresce. Porque uma multa isolada por capacete pode até parecer burocracia. Mas quando acontece numa abordagem tão observada, com viatura parada, luz acesa e curiosos cochichando, a coisa ganha outro cheiro.</p>
<p>Se era só trânsito, foi rigor demais. Se não era só trânsito, falta explicar o resto. A <strong style="color:#cc0000">Red News</strong> vai acompanhar de perto, porque Montgomery anda calma demais na superfície e barulhenta demais nos bastidores.</p>
<div class="resumo">
  <div class="resumo-ttl">O que se sabe</div>
  <div class="resumo-item"><span class="rdot"></span><span>Um homem não identificado foi multado por falta de capacete.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>Testemunhas dizem que ele estava parado no momento da abordagem.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>Moradores relatam aumento do rigor dos sheriffs em Montgomery.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>A dúvida na cidade: fiscalização comum ou busca por algo maior?</span></div>
</div>
"""

MONTGOMERY_TASER_BODY = """
<p><strong style="color:#cc0000">Era para ser so mais uma noite na fila da Stacked Pizza.</strong> Virou caso de taser, viatura parada e uma pergunta atravessando Montgomery de ponta a ponta: o novo sheriff chegou para proteger a cidade ou para medir forca com morador?</p>
<p>Segundo relatos enviados a <strong style="color:#cc0000">Red News</strong>, a confusao comecou na entrada da Stacked, onde moradores aguardavam atendimento e discutiam a ordem da fila. O clima subiu, o sheriff se aproximou e, em poucos minutos, o que era boca a boca virou cena de abordagem.</p>
<figure style="margin:28px 0">
  <img src="assets/montgomery-sheriff-taser-1.png" alt="Sheriff encara morador em Montgomery" style="width:100%;border-radius:8px">
  <figcaption style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#777;line-height:1.5;margin-top:10px">O novo sheriff frente a frente com o morador antes da confusao ganhar proporcao.</figcaption>
</figure>
<h2><strong style="color:#cc0000">A FILA QUE VIROU CASO DE POLICIA</strong></h2>
<p>Quem estava por perto diz que a discussao era de fila. Sim, fila. Aquele tipo de atrito besta que normalmente termina com alguem reclamando alto e outro fingindo que nao ouviu. Mas em Montgomery, ultimamente, nada parece terminar no normal.</p>
<p>Testemunhas afirmam que o morador questionou a movimentacao na entrada e apontou para a fila. Foi o suficiente para o sheriff endurecer a postura. A conversa azedou, a viatura ficou em destaque e a rua entendeu o recado: <strong style="color:#cc0000">a paciencia do departamento parece mais curta do que nunca</strong>.</p>
<figure style="margin:28px 0">
  <img src="assets/montgomery-sheriff-taser-2.png" alt="Morador aponta durante discussao na Stacked Pizza" style="width:100%;border-radius:8px">
  <figcaption style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#777;line-height:1.5;margin-top:10px">Morador aponta em direcao a fila da Stacked enquanto o sheriff observa a cena.</figcaption>
</figure>
<blockquote>
  <p>"Foi coisa de fila. Do nada, parecia que o cara tinha virado ameaca publica."</p>
  <div class="bq-author">Morador que acompanhou a confusao</div>
</blockquote>
<h2><strong style="color:#cc0000">TASER NO MORADOR</strong></h2>
<p>A parte que incendiou Montgomery veio depois: relatos indicam que o sheriff usou <strong style="color:#cc0000">disparo de taser</strong> contra o morador apos a discussao. Nao estamos falando de perseguidor armado, assalto em andamento ou fuga cinematografica. Estamos falando de uma confusao na entrada de uma pizzaria.</p>
<p>Nas imagens, o morador aparece proximo ao veiculo policial e depois no chao, enquanto o oficial se aproxima. A versao do departamento ainda nao veio, mas a cidade ja escolheu o tema do dia: <strong style="color:#cc0000">rigor ou abuso de autoridade?</strong></p>
<figure style="margin:28px 0">
  <img src="assets/montgomery-sheriff-taser-4.png" alt="Morador no chao apos abordagem com taser" style="width:100%;border-radius:8px">
  <figcaption style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#777;line-height:1.5;margin-top:10px">Momento em que o morador aparece no chao durante a abordagem ao lado da viatura.</figcaption>
</figure>
<h2><strong style="color:#cc0000">MONTGOMERY NA MIRA DOS SD?</strong></h2>
<p>A Red News vem recebendo relatos de moradores dizendo que o novo sheriff estaria <strong style="color:#cc0000">marcando presenca demais</strong> na cidade. Abordagens, olhares longos, perguntas em excesso e aquela sensacao de que qualquer detalhe pode virar ocorrencia.</p>
<p>Claro, sheriff vai dizer que e rotina. Sempre e. Mas a rua nao engole tudo. Para muita gente, Montgomery virou palco de uma operacao silenciosa: ninguem sabe exatamente o que os SD procuram, mas todo mundo sente que eles procuram alguma coisa.</p>
<figure style="margin:28px 0">
  <img src="assets/montgomery-sheriff-taser-3.png" alt="Sheriff conversa com morador ao lado de viatura" style="width:100%;border-radius:8px">
  <figcaption style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#777;line-height:1.5;margin-top:10px">Abordagem registrada ao lado da viatura: moradores falam em clima de pressao na cidade.</figcaption>
</figure>
<p>Se o objetivo era organizar a entrada da Stacked, o resultado foi outro: <strong style="color:#cc0000">um morador no chao, a cidade comentando e o departamento de sheriff no centro da suspeita</strong>. A Red News vai seguir de olho, porque quando a fila da pizza vira caso de taser, alguma coisa saiu muito do lugar.</p>
<div class="resumo">
  <div class="resumo-ttl">Entenda o caso</div>
  <div class="resumo-item"><span class="rdot"></span><span>Novo sheriff entrou em atrito com morador em Montgomery.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>A confusao teria comecado por causa da fila da Stacked Pizza.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>Relatos apontam uso de taser contra o morador apos a discussao.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>Moradores dizem que os SD estao aumentando a pressao na cidade.</span></div>
</div>
"""

def seed_montgomery_helmet_article():
    conn = get_db(); cur = conn.cursor()
    db_execute(cur,
        'INSERT INTO news (id,type,icon,cat,title,"desc",body,image_url,time_str,label,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET type=EXCLUDED.type,icon=EXCLUDED.icon,cat=EXCLUDED.cat,title=EXCLUDED.title,"desc"=EXCLUDED."desc",body=EXCLUDED.body,image_url=EXCLUDED.image_url,time_str=EXCLUDED.time_str,label=EXCLUDED.label,created_at=EXCLUDED.created_at',
        ("d3", "featured", "⚡", "Policial",
         "Taser na fila da Stacked: novo sheriff compra briga com morador",
         "Relatos em Montgomery dizem que o novo sheriff vem perseguindo moradores. Desta vez, uma confusao por fila terminou com taser e revolta.",
         MONTGOMERY_TASER_BODY, "assets/montgomery-sheriff-taser-4.png",
         "Hoje, 15/06", "EXCLUSIVO", int(time.time()) + 90)
    )
    conn.commit(); cur.close(); conn.close()

SILENCIO_DISTINTIVO_BODY = """
<div style="text-align:center;margin:0 0 28px">
  <div style="font-family:'Share Tech Mono',monospace;font-size:12px;letter-spacing:2px;color:#b30000;text-transform:uppercase;margin-bottom:14px">Red News • Red County • Crônica de Opinião</div>
  <h2 style="border:none;padding:0;margin:0 0 14px;font-size:34px;color:#f3f3ef">O silêncio também usa distintivo</h2>
  <p style="font-family:'Source Serif 4',serif;font-size:18px;line-height:1.55;color:#d2d2cc;margin:0 auto;max-width:680px"><strong style="color:#b30000">Um taser, uma fila de pizza e um morador no chão.</strong> O departamento não explica, e em Red County já se aprendeu que silêncio de quem anda armado raramente é inocente.</p>
  <div style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#777;margin-top:16px">Por <strong style="color:#ddd">Beau Hollister</strong> • Red News • Red County</div>
</div>
<hr>
<p>Começo com uma confissão de método: não acuso ninguém. Apenas reparo. E reparar, em Red County, anda virando esporte de risco. Desde que o novo xerife assumiu Montgomery, a cidade aprendeu a abaixar a voz quando a viatura passa. Chamam isso de ordem. Eu, que sou de jornal pequeno, prefiro chamar pelo nome técnico mais tarde, quando o departamento já tiver ido dormir.</p>
<p>O caso é quase didático de tão pequeno. Uma fila. A fila da Stacked Pizza. Aquele atrito bobo que, em qualquer cidade do mundo, termina com um reclamando alto e outro fingindo que não ouviu. Em Montgomery, terminou com <strong style="color:#b30000">taser, viatura em destaque e um morador no chão</strong>. Não havia assaltante. Não havia fuga. Havia gente com fome esperando pizza. E, ainda assim, alguém decidiu que o caso pedia choque elétrico.</p>
<p>Quem estava lá contou uma coisa que me persegue desde ontem. Quando o homem caiu, a rua não comemorou. Ficou quieta. Não foi alívio, foi medo. E eu pergunto, com toda a delicadeza de quem só repara: <strong style="color:#b30000">a quem interessa uma Montgomery com medo?</strong> Porque medo é péssimo para quem só queria atravessar a calçada, e curiosamente ótimo para quem precisa que ninguém pergunte nada.</p>
<p>Reparei também numa coincidência dessas que o departamento vai jurar que é acaso. A mão do novo xerife é rápida com o morador de bolso vazio na esquina errada. Para o sujeito de fila, de boné, de carro velho, o relógio anda. Eu não estou dizendo que a farda escolhe endereço. Estou dizendo que, se escolhesse, a cena seria exatamente essa que Montgomery viu. E quando a hipótese coincide com o fato com tanta perfeição, fica difícil continuar chamando de coincidência.</p>
<p>O distintivo é uma concessão da população, não um título de nobreza. Mas tem gente vestindo a farda como quem veste poder pessoal, tratando a cidade como propriedade de fim de semana. Quando esse tipo de autoridade age e depois se cala, não chamo de descuido. Descuido se corrige. <strong style="color:#b30000">Isso parece método.</strong> Quem trabalha limpo não tem medo de pergunta. Quem foge da pergunta, em geral, está cuidando para que ela não chegue perto demais.</p>
<p>Dirão que é cedo para cobrar. Engraçado como o relógio do departamento é seletivo. Para abordar, para revistar, para encostar o taser, nunca é cedo. Mas para prestar contas ao povo que paga essa farda, de repente todos descobrem a lentidão dos procedimentos e a poesia burocrática do "estamos apurando". Apurando o quê, exatamente? A própria conta?</p>
<p>Que não me entendam mal, e os defensores de plantão vão fazer questão de não entender. Eu defendo polícia. Defendo a que protege a velhinha, prende o bandido de verdade e aparece quando a gente precisa, não quando a gente reclama da fila. O que não dá para defender é <strong style="color:#b30000">farda confundida com coroa</strong> e cidadão tratado como suspeito por crime de impaciência. Existe diferença entre segurança pública e capitania hereditária, e o novo xerife parece ter pulado esse capítulo.</p>
<p>E não foi a primeira abordagem pesada da semana, segundo moradores que falam baixo porque amanhã a viatura pode parar na porta de casa. Aí mora a pergunta velha e incômoda: quem fiscaliza o xerife? Em Montgomery, ao que tudo indica, ninguém. E onde ninguém fiscaliza, o abuso deixa de ser exceção e vira paisagem. "É assim mesmo", já começam a dizer. Não, não é. É assim porque alguém decidiu que fosse, e está achando confortável.</p>
<p>Deixo então as perguntas que o departamento não vai responder, mas que a cidade já respondeu sozinha: <strong style="color:#b30000">o que justifica um taser numa discussão de fila?</strong> Quem autorizou? Houve perigo real, ou só um ego de farda nova precisando de plateia? E por que, com a foto do morador no chão rodando Montgomery inteira, o silêncio oficial continua mais firme do que aperto de mão de político em ano de eleição?</p>
<p>Repito que não acuso. Só reparo. Reparo que a Stacked queria vender pizza e acabou vendendo um retrato de Red County: o cidadão no chão, a farda em pé e o poder público de costas. Os novos xerifes vieram proteger a cidade ou ensinar a cidade a ter medo? A resposta, como sempre, não está no volume da sirene. Está no silêncio que vem depois dela. E <strong style="color:#b30000">silêncio de quem tem arma, distintivo e nada a explicar</strong> nunca foi, em lugar nenhum, sinal de inocência.</p>
<hr>
<p style="text-align:center;font-size:15px;color:#aaa;font-style:italic">Esta crônica não condena antes dos fatos. Apenas lembra que, numa cidade livre, quem dispara um taser numa fila de pizza deve à população algo mais do que silêncio: deve uma explicação que caiba na luz do dia.</p>
"""

def seed_silencio_distintivo_cronica():
    conn = get_db(); cur = conn.cursor()
    db_execute(cur,
        'INSERT INTO news (id,type,icon,cat,title,"desc",body,image_url,time_str,label,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET type=EXCLUDED.type,icon=EXCLUDED.icon,cat=EXCLUDED.cat,title=EXCLUDED.title,"desc"=EXCLUDED."desc",body=EXCLUDED.body,image_url=EXCLUDED.image_url,time_str=EXCLUDED.time_str,label=EXCLUDED.label,created_at=EXCLUDED.created_at',
        ("silencio-distintivo-2026-06-16", "item", "✒", "Crônica",
         "O silêncio também usa distintivo",
         "Um taser, uma fila de pizza e um morador no chão. O departamento não explica, e em Red County silêncio de quem anda armado raramente é inocente.",
         SILENCIO_DISTINTIVO_BODY, "assets/beau-hollister-lupa.png",
         "Hoje, 16/06", "OPINIÃO", int(time.time()) + 80)
    )
    conn.commit(); cur.close(); conn.close()

BAR_DO_JOE_ATTACK_BODY = """
<p><strong style="color:#cc0000">Por volta das 23h40 de ontem</strong>, com a cidade quase toda dormindo, o Bar do Joe, em Montgomery, virou cena de crime. Um morador de rua, apontado por frequentadores como usuário conhecido na cidade, entrou no estabelecimento, partiu para cima do garçom e, minutos depois, estava morto no chão de madeira atrás do balcão.</p>
<p>A <strong style="color:#cc0000">Red News</strong> esteve no local depois do isolamento. Segundo relatos de quem estava presente, o morador de rua não chegou procurando confusão de bar. Chegou procurando <strong style="color:#cc0000">Klaus</strong>, o garçom que trabalha naquele balcão há anos.</p>
<figure style="margin:28px 0">
  <img src="assets/bar-do-joe-ataque-7.jpg?v=3cf802b" alt="Fita de isolamento cruzando o balcão do Bar do Joe" style="width:100%;border-radius:8px">
  <figcaption style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#777;line-height:1.5;margin-top:10px">Fita de isolamento cruzando o balcão do Bar do Joe após a tentativa de homicídio.</figcaption>
</figure>
<h2><strong style="color:#cc0000">ELE NÃO VEIO BEBER</strong></h2>
<p>A frase é de uma testemunha que pediu para não ser identificada. O homem teria desferido uma tacada contra Klaus e tentado matá-lo ali mesmo, na frente dos outros clientes.</p>
<p>Não contava com a reação. Outro homem que estava no balcão sacou uma faca e revidou. Em segundos, a tentativa de assassinato virou <strong style="color:#cc0000">um corpo no chão</strong>.</p>
<figure style="margin:28px 0">
  <img src="assets/bar-do-joe-ataque-3.jpg?v=3cf802b" alt="Sheriffs no interior do bar após o isolamento" style="width:100%;border-radius:8px">
  <figcaption style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#777;line-height:1.5;margin-top:10px">Sheriffs no interior do bar após o isolamento. Testemunhas foram mantidas longe da área do balcão.</figcaption>
</figure>
<h2><strong style="color:#cc0000">O MORADOR NÃO SAIU VIVO</strong></h2>
<p>O homem caiu no meio da confusão e não resistiu. O corpo permaneceu no local até a chegada da polícia, que cercou tudo com a fita amarela de praxe: <strong style="color:#cc0000">SHERIFF'S LINE — DO NOT CROSS</strong>. O Bar do Joe segue interditado enquanto a investigação corre.</p>
<p>Até o fechamento desta matéria, os sheriffs não haviam divulgado a identidade do morador de rua nem confirmado oficialmente a motivação do ataque.</p>
<figure style="margin:28px 0">
  <img src="assets/bar-do-joe-ataque-1.jpg?v=3cf802b" alt="Corpo atrás do balcão do Bar do Joe" style="width:100%;border-radius:8px">
  <figcaption style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#777;line-height:1.5;margin-top:10px">O corpo ficou estendido atrás do balcão até o isolamento da área.</figcaption>
</figure>
<blockquote>
  <p>"O balcão do Joe não é terra sem lei. Ontem um deles descobriu isso da pior forma."</p>
  <div class="bq-author">Beau Hollister, Red News</div>
</blockquote>
<h2><strong style="color:#cc0000">OPINIÃO: MONTGOMERY NÃO É TERRA DE NINGUÉM</strong></h2>
<p>E aqui vai o recado, porque alguém precisa dar. Cansei de ver gente entrando armada nos nossos estabelecimentos como se a lei aqui fosse decoração. Não é. Ontem um usuário conhecido na cidade aprendeu isso do jeito mais caro que existe.</p>
<p><strong style="color:#cc0000">Melhor a mãe desse tipo chorando do que a de um trabalhador honesto.</strong> A Red News vai acompanhar a investigação até o fim. Se você viu alguma coisa, sabe onde achar Beau Hollister.</p>
<figure style="margin:28px 0">
  <img src="assets/bar-do-joe-ataque-6.jpg?v=3cf802b" alt="Cena isolada no Bar do Joe" style="width:100%;border-radius:8px">
  <figcaption style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#777;line-height:1.5;margin-top:10px">A área do balcão foi isolada enquanto os sheriffs avaliavam a cena.</figcaption>
</figure>
<p><strong style="color:#cc0000">Klaus segue vivo. O outro, não.</strong></p>
<div class="resumo">
  <div class="resumo-ttl">O que se sabe até agora</div>
  <div class="resumo-item"><span class="rdot"></span><span>Por volta das 23h40, um morador de rua entrou transtornado no Bar do Joe, em Montgomery.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>O alvo foi Klaus, garçom conhecido do balcão.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>O homem, apontado como usuário conhecido na cidade, desferiu uma tacada e tentou matá-lo na frente dos clientes.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>Um presente reagiu com faca durante a confusão.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>O morador de rua morreu no local. O bar foi interditado pelos sheriffs.</span></div>
</div>
"""

def seed_bar_do_joe_attack_article():
    conn = get_db(); cur = conn.cursor()
    db_execute(cur,
        'INSERT INTO news (id,type,icon,cat,title,"desc",body,image_url,time_str,label,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET type=EXCLUDED.type,icon=EXCLUDED.icon,cat=EXCLUDED.cat,title=EXCLUDED.title,"desc"=EXCLUDED."desc",body=EXCLUDED.body,image_url=EXCLUDED.image_url,time_str=EXCLUDED.time_str,label=EXCLUDED.label,created_at=EXCLUDED.created_at',
        ("bar-do-joe-noite-sangue-2026-06-17", "featured", "🩸", "Policial",
         "Noite de sangue no Bar do Joe: morador de rua tenta matar garçom e morre esfaqueado no balcão",
         "Klaus sobreviveu. O morador de rua, usuário conhecido na cidade, não. O estabelecimento foi interditado pelos sheriffs após a tentativa de homicídio e a reação fatal.",
         BAR_DO_JOE_ATTACK_BODY, "assets/bar-do-joe-ataque-7.jpg?v=3cf802b",
         "Hoje, 17/06", "EDIÇÃO DE EMERGÊNCIA", int(time.time()) + 160)
    )
    conn.commit(); cur.close(); conn.close()

MONTGORE_BODY = """
<p><strong style="color:#cc0000">E aqui vai, porque alguém precisa dizer.</strong></p>
<p>Bem-vindo a <strong style="color:#cc0000">Montgore</strong>. A cidade que ainda insiste em se chamar Montgomery transformou uma festa de sinuca em frente ao Bar do Joe no pior banho de sangue do ano. Três corpos no chão, dois feridos, e uma segurança pública que, mais uma vez, só apareceu para contar os mortos.</p>
<p>Segundo testemunhas, tudo começou com um homem identificado como <strong style="color:#cc0000">Nikita</strong>. Ele se meteu numa briga no meio da festa e, no calor da discussão, sacou e baleou um idoso, até agora não identificado, que não tinha nada a ver com aquilo. O senhor caiu ali mesmo, na frente de todo mundo que tinha ido só beber e jogar.</p>
<figure style="margin:28px 0">
  <img src="https://i.imgur.com/0EHaavx.png" alt="Idoso baleado caído na via" style="width:100%;border-radius:8px">
  <figcaption style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#777;line-height:1.5;margin-top:10px">Idoso baleado caído na via enquanto os xerifes assumem a cena. Montgomery, 17/06.</figcaption>
</figure>
<h2><strong style="color:#cc0000">NIKITA SUMIU, VOLTOU E TRANSFORMOU A PRAÇA EM GUERRA</strong></h2>
<p>Nikita fugiu. E aqui mora a primeira pergunta que o Departamento do Xerife vai querer enterrar: como um homem atira numa praça lotada e simplesmente some por alguns minutos? Porque sumiu. O SD saiu em perseguição e só voltou a ter Nikita no radar quando ele reapareceu, em alta, e colidiu o carro bem no meio da praça.</p>
<p>Não se entregou. Desceu do veículo atirando contra os policiais. A essa altura, a festa já tinha virado zona de guerra.</p>
<figure style="margin:28px 0">
  <img src="https://i.imgur.com/nJVPNJ1.png" alt="Praça tomada por viaturas e ambulância" style="width:100%;border-radius:8px">
  <figcaption style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#777;line-height:1.5;margin-top:10px">A praça tomada por viaturas, ambulância e o caos depois da colisão.</figcaption>
</figure>
<h2><strong style="color:#cc0000">A SOCORRISTA QUE LEVOU TIRO DE QUEM DEVIA PROTEGER</strong></h2>
<p>E é no meio dessa troca de tiros que Montgomery sai do caos e entra na vergonha pura. Enquanto Nikita disparava, a equipe da <strong style="color:#cc0000">FIRE</strong> estava ajoelhada no chão tentando salvar o idoso baleado no início de tudo. Fazendo o trabalho mais honesto daquela praça inteira.</p>
<p>Foi quando a socorrista <strong style="color:#cc0000">Amanda Foster</strong> levou um tiro. Não do bandido. De um <strong style="color:#cc0000">xerife</strong> que tentava acertar Nikita e acertou quem estava salvando uma vida.</p>
<blockquote>
  <p>Em Montgore, até a bala que devia proteger você acha primeiro quem foi te socorrer.</p>
  <div class="bq-author">Klaus Vogel, Red News</div>
</blockquote>
<figure style="margin:28px 0">
  <img src="https://i.imgur.com/w6oBRZg.png" alt="Equipe da FIRE em atendimento no asfalto" style="width:100%;border-radius:8px">
  <figcaption style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#777;line-height:1.5;margin-top:10px">Equipe da FIRE em atendimento no asfalto, instantes antes do disparo que feriu a socorrista.</figcaption>
</figure>
<h2><strong style="color:#cc0000">O SEGUNDO ATIRADOR ESTAVA NO MEIO DOS CURIOSOS</strong></h2>
<p>E não acabou ali. Com a cena ainda fervendo, nossa equipe flagrou o detalhe que escancara o tamanho do descontrole: um <strong style="color:#cc0000">homem de capuz cinza</strong>, que estava misturado entre os curiosos, saiu do meio da multidão e começou a disparar contra os xerifes. Estava ali o tempo todo. Ninguém viu. Ninguém isolou. Ninguém fez o perímetro.</p>
<figure style="margin:28px 0">
  <img src="https://i.imgur.com/MWFGOGc.png" alt="Segundo atirador encapuzado entre curiosos" style="width:100%;border-radius:8px">
  <figcaption style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#777;line-height:1.5;margin-top:10px">Flagrante: o segundo atirador encapuzado se desloca por trás dos curiosos momentos antes de abrir fogo.</figcaption>
</figure>
<p>O encapuzado também foi neutralizado e morreu no local. Mas antes disso, conseguiu o que um homem sozinho jamais deveria conseguir contra uma corporação inteira: feriu um deles. O xerife <strong style="color:#cc0000">Edward McClanahan</strong> saiu baleado da própria operação que devia estar sob controle.</p>
<figure style="margin:28px 0">
  <img src="https://i.imgur.com/lLpUFb4.png" alt="Xerife Edward McClanahan ferido" style="width:100%;border-radius:8px">
  <figcaption style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#777;line-height:1.5;margin-top:10px">O xerife Edward McClanahan ferido, ao lado de Jose Escuella, após o segundo ataque.</figcaption>
</figure>
<h2><strong style="color:#cc0000">TRÊS MORTOS, DOIS FERIDOS E UMA CIDADE REFÉM DO IMPROVISO</strong></h2>
<p>No fim, o saldo de Montgore: <strong style="color:#cc0000">três mortos</strong>, entre eles o idoso que a FIRE não conseguiu salvar porque atiraram em quem o salvava, e <strong style="color:#cc0000">dois feridos</strong>, a socorrista Amanda Foster e o xerife Edward McClanahan.</p>
<p>Chamam isso de resposta rápida. Eu chamo de colheita tardia. Porque quando o atirador foge, some, volta de carro, bate na praça, desce atirando, e ainda sobra brecha para um segundo homem sair do meio da multidão disparando, o problema deixou de ser o bandido. O problema é uma segurança pública que trata toda tragédia como se fosse a primeira, toda santa vez.</p>
<p>O pequeno paga primeiro. Sempre. Paga quem foi jogar sinuca. Paga quem foi socorrer e levou bala de quem jurou protegê-la. Paga a cidade que finge não ter virado o que virou.</p>
<div class="resumo">
  <div class="resumo-ttl">O que se sabe até agora</div>
  <div class="resumo-item"><span class="rdot"></span><span>A festa de sinuca em frente ao Bar do Joe reunia moradores quando começou o primeiro ataque.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span><strong>Nikita</strong> se envolveu numa briga e baleou um idoso não identificado.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>Nikita fugiu, foi perseguido pelo SD e colidiu o carro na praça.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>Ao descer do veículo, abriu fogo contra os xerifes e foi neutralizado.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>A socorrista da FIRE <strong>Amanda Foster</strong> foi atingida por disparo de um xerife que mirava Nikita.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>Um segundo atirador de capuz cinza feriu <strong>Edward McClanahan</strong> antes de morrer no local.</span></div>
  <div class="resumo-item"><span class="rdot"></span><span>Saldo final: <strong>três mortos e dois feridos</strong>.</span></div>
</div>
<h2><strong style="color:#cc0000">MONTGOMERY JÁ É MAIS LETAL QUE IDLEWOOD</strong></h2>
<p>E para quem ainda acha exagero chamar de Montgore, os números não deixam mentir. Levantamento da Red News aponta que, no primeiro semestre de <strong style="color:#cc0000">2026</strong>, Montgomery registrou <strong style="color:#cc0000">17,4 homicídios por mil habitantes</strong>. Idlewood, o endereço mais temido de Los Santos, fechou o mesmo período com <strong style="color:#cc0000">11,2</strong>.</p>
<p>Leu certo. A nossa pacata cidade do interior é hoje <strong style="color:#cc0000">55% mais letal</strong> que a favela que o resto do estado usa como sinônimo de perigo. Uma morte violenta a cada 26 horas, e subindo.</p>
<p>Montgomery não precisa de mais nota ensaiada nem de coletiva dizendo que está tudo sob controle. Precisa de uma segurança pública que não dependa do terceiro tiro para acordar. A Red News vai acompanhar essa história até o fim. E toda vez que tentarem empurrar a culpa para o acaso, eu vou lembrar que bala até se perde, mas incompetência sempre acha endereço.</p>
<p style="text-align:right"><strong style="color:#cc0000">Klaus Vogel</strong><br><span style="color:#777;font-style:italic">Red News • Rádio • Jornal • Red County</span></p>
"""

def seed_montgore_article():
    conn = get_db(); cur = conn.cursor()
    db_execute(cur,
        'INSERT INTO news (id,type,icon,cat,title,"desc",body,image_url,time_str,label,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET type=EXCLUDED.type,icon=EXCLUDED.icon,cat=EXCLUDED.cat,title=EXCLUDED.title,"desc"=EXCLUDED."desc",body=EXCLUDED.body,image_url=EXCLUDED.image_url,time_str=EXCLUDED.time_str,label=EXCLUDED.label,created_at=EXCLUDED.created_at',
        ("montgore-noite-de-sangue-2026-06-17", "featured", "🚨", "Policial",
         "Montgore: três mortos e dois feridos colocam Montgomery acima de Idlewood",
         "Festa de sinuca termina em praça tomada por tiros, socorrista baleada por xerife e segundo atirador surgindo do meio dos curiosos.",
         MONTGORE_BODY, "assets/montgore-cover.jpg?v=gallery103",
         "Hoje, 17/06", "EDIÇÃO DE EMERGÊNCIA", int(time.time()) + 420)
    )
    conn.commit(); cur.close(); conn.close()

def seed_montgore_comments():
    article_id = "montgore-noite-de-sangue-2026-06-17"
    base = int(time.time()) - (10 * 3600)
    comments = [
        ("montgore-c1", None, "Raimundo Torres", "Montgore foi o nome mais certo que a Red News já inventou. Três mortos numa noite e ainda tem gente dizendo que está tudo normal.", 9, base + 180),
        ("montgore-c2", None, "Selma K.", "O que mais me revolta é a Amanda levando tiro enquanto tentava salvar o idoso. Isso não é azar, é despreparo.", 13, base + 3900),
        ("montgore-c3", "montgore-c2", "Duque", "Exatamente. Quem atira com FIRE ajoelhada no chão precisa responder, simples assim.", 5, base + 4560),
        ("montgore-c4", None, "Tremaine Hill", "Eu estava perto do bar e ninguém isolou nada direito. Tinha curioso passando como se fosse desfile.", 7, base + 7500),
        ("montgore-c5", "montgore-c4", "Marta de Blueberry", "Aí depois dizem que a culpa é do povo olhando. Se não tem perímetro, o povo vai ficar onde?", 4, base + 8160),
        ("montgore-c6", None, "Josefina M.", "Nikita era problema anunciado. Todo mundo já tinha visto esse homem procurando confusão antes.", 6, base + 11100),
        ("montgore-c7", None, "Calvin Price", "Não passo mais em Montgomery à noite. Idlewood pelo menos assume o que é. Aqui fingem que é cidade tranquila.", 10, base + 14640),
        ("montgore-c8", "montgore-c7", "Beto do Guincho", "Falaram que era exagero da Red News. Agora tem número: 17,4 por mil. Quero ver chamar de fofoca.", 8, base + 15300),
        ("montgore-c9", None, "Lena Foster", "Sou parente de socorrista e digo: FIRE entra para salvar, não para virar alvo de erro dos outros.", 12, base + 18840),
        ("montgore-c10", "montgore-c9", "Arlindo", "Força pra Amanda. E investigação de verdade, não nota bonitinha de departamento.", 6, base + 22500),
    ]
    conn = get_db(); cur = conn.cursor()
    for c in comments:
        db_execute(cur,
            "INSERT INTO comments (id,article_id,parent_id,author,body,likes,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
            (c[0], article_id, c[1], c[2], c[3], c[4], c[5])
        )
    conn.commit(); cur.close(); conn.close()

init_db()

# ── Auth helper ───────────────────────────────────────────────────────────────

ENV_ADMIN_PWD = os.environ.get("ADMIN_PASSWORD", "")

def require_admin_enabled():
    if not ADMIN_ENABLED:
        raise HTTPException(404, "Admin desativado")

def verify_token(
    authorization: Optional[str] = Header(None),
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    if ADMIN_API_KEY and x_admin_key and secrets.compare_digest(x_admin_key, ADMIN_API_KEY):
        return "admin-api-key"
    require_admin_enabled()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Não autorizado")
    token = authorization[7:]
    conn = get_db(); cur = conn.cursor()
    db_execute(cur, "SELECT created_at FROM tokens WHERE token=%s", (token,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        raise HTTPException(401, "Token inválido")
    if time.time() - row["created_at"] > TOKEN_TTL:
        conn = get_db(); cur = conn.cursor()
        db_execute(cur, "DELETE FROM tokens WHERE token=%s", (token,))
        conn.commit(); cur.close(); conn.close()
        raise HTTPException(401, "Sessão expirada")
    return token

def new_token():
    token = secrets.token_hex(32)
    conn = get_db(); cur = conn.cursor()
    db_execute(cur, "INSERT INTO tokens (token,created_at) VALUES (%s,%s)", (token, int(time.time())))
    conn.commit(); cur.close(); conn.close()
    return token

def _check_password(plain: str) -> bool:
    h = hashlib.sha256(plain.encode()).hexdigest()
    if ENV_ADMIN_PWD:
        return plain == ENV_ADMIN_PWD
    conn = get_db(); cur = conn.cursor()
    db_execute(cur, "SELECT value FROM settings WHERE key='admin_hash'")
    row = cur.fetchone()
    cur.close(); conn.close()
    return bool(row) and h == row["value"]

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

class TickerUpdate(BaseModel):
    text: Optional[str] = None
    use_custom: Optional[bool] = None

class CommentItem(BaseModel):
    author: str
    body: str
    parent_id: Optional[str] = None

class SponsorUpdate(BaseModel):
    name: Optional[str] = None
    tagline: Optional[str] = None
    cta_text: Optional[str] = None
    cta_url: Optional[str] = None
    image_url: Optional[str] = None
    theme: Optional[str] = None

COMMENT_ALIASES = {
    "s1": "solevan-2026-06-11",
}

def canonical_article_id(article_id: str) -> str:
    return COMMENT_ALIASES.get(article_id, article_id)

def comment_article_ids(article_id: str):
    canonical = canonical_article_id(article_id)
    aliases = [canonical]
    aliases.extend(k for k, v in COMMENT_ALIASES.items() if v == canonical)
    return aliases

# ── Auth endpoints ────────────────────────────────────────────────────────────

@app.get("/api/auth/status")
def auth_status():
    if not ADMIN_ENABLED:
        return {"enabled": False, "has_password": False}
    if ENV_ADMIN_PWD:
        return {"enabled": True, "has_password": True}
    conn = get_db(); cur = conn.cursor()
    db_execute(cur, "SELECT 1 FROM settings WHERE key='admin_hash'")
    has = bool(cur.fetchone())
    cur.close(); conn.close()
    return {"enabled": True, "has_password": has}

@app.post("/api/auth/setup")
def setup_password(req: SetupReq):
    require_admin_enabled()
    if ENV_ADMIN_PWD:
        if not _check_password(req.password):
            raise HTTPException(401, "Senha incorreta")
        return {"token": new_token()}
    conn = get_db(); cur = conn.cursor()
    db_execute(cur, "SELECT 1 FROM settings WHERE key='admin_hash'")
    if cur.fetchone():
        cur.close(); conn.close()
        raise HTTPException(400, "Senha já configurada")
    if len(req.password) < 6:
        cur.close(); conn.close()
        raise HTTPException(400, "Mínimo 6 caracteres")
    h = hashlib.sha256(req.password.encode()).hexdigest()
    db_execute(cur, "INSERT INTO settings (key,value) VALUES ('admin_hash',%s)", (h,))
    conn.commit(); cur.close(); conn.close()
    return {"token": new_token()}

@app.post("/api/auth/login")
def login(req: LoginReq):
    require_admin_enabled()
    if not _check_password(req.password):
        raise HTTPException(401, "Senha incorreta")
    return {"token": new_token()}

@app.post("/api/auth/logout")
def logout(token: str = Depends(verify_token)):
    conn = get_db(); cur = conn.cursor()
    db_execute(cur, "DELETE FROM tokens WHERE token=%s", (token,))
    conn.commit(); cur.close(); conn.close()
    return {"ok": True}

@app.post("/api/auth/change")
def change_password(req: ChangePwdReq, token: str = Depends(verify_token)):
    if len(req.new_password) < 6:
        raise HTTPException(400, "Mínimo 6 caracteres")
    conn = get_db(); cur = conn.cursor()
    db_execute(cur, "SELECT value FROM settings WHERE key='admin_hash'")
    row = cur.fetchone()
    if not row or hashlib.sha256(req.current_password.encode()).hexdigest() != row["value"]:
        cur.close(); conn.close()
        raise HTTPException(401, "Senha atual incorreta")
    h = hashlib.sha256(req.new_password.encode()).hexdigest()
    db_execute(cur, "UPDATE settings SET value=%s WHERE key='admin_hash'", (h,))
    conn.commit(); cur.close(); conn.close()
    return {"ok": True}

@app.post("/api/auth/reset")
def factory_reset(token: str = Depends(verify_token)):
    conn = get_db(); cur = conn.cursor()
    db_execute(cur, "DELETE FROM settings")
    db_execute(cur, "DELETE FROM news")
    db_execute(cur, "DELETE FROM tokens")
    conn.commit(); cur.close(); conn.close()
    seed_news()
    return {"ok": True}

# ── News endpoints ────────────────────────────────────────────────────────────

@app.get("/api/news")
def get_news():
    conn = get_db(); cur = conn.cursor()
    db_execute(cur, 'SELECT id,type,icon,cat,title,"desc",body,image_url,time_str,label,created_at FROM news ORDER BY created_at DESC')
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]

@app.post("/api/news")
def add_news(item: NewsItem, token: str = Depends(verify_token)):
    nid = secrets.token_hex(8)
    conn = get_db(); cur = conn.cursor()
    db_execute(cur,
        'INSERT INTO news (id,type,icon,cat,title,"desc",body,image_url,time_str,label,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (nid, item.type, item.icon, item.cat, item.title, item.desc, item.body, item.image_url, item.time, item.label, int(time.time()))
    )
    conn.commit(); cur.close(); conn.close()
    return {"id": nid}

@app.put("/api/news/{news_id}")
def edit_news(news_id: str, data: NewsEdit, token: str = Depends(verify_token)):
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if fields:
        conn = get_db(); cur = conn.cursor()
        col_map = {"desc": '"desc"'}
        sets = ", ".join(f"{col_map.get(k,k)}=%s" for k in fields)
        db_execute(cur, f"UPDATE news SET {sets} WHERE id=%s", (*fields.values(), news_id))
        conn.commit(); cur.close(); conn.close()
    return {"ok": True}

@app.delete("/api/news/{news_id}")
def delete_news(news_id: str, token: str = Depends(verify_token)):
    conn = get_db(); cur = conn.cursor()
    db_execute(cur, "DELETE FROM news WHERE id=%s", (news_id,))
    conn.commit(); cur.close(); conn.close()
    return {"ok": True}

@app.post("/api/news/reset")
def reset_news(token: str = Depends(verify_token)):
    conn = get_db(); cur = conn.cursor()
    db_execute(cur, "DELETE FROM news")
    conn.commit(); cur.close(); conn.close()
    seed_news()
    return {"ok": True}

# ── Stream endpoints ──────────────────────────────────────────────────────────

@app.get("/api/stream")
def get_stream():
    conn = get_db(); cur = conn.cursor()
    db_execute(cur, "SELECT key,value FROM settings WHERE key IN ('stream_url','is_live')")
    rows = {r["key"]: r["value"] for r in cur.fetchall()}
    cur.close(); conn.close()
    url = rows.get("stream_url") or DEFAULT_STREAM_URL
    return {
        "url": url,
        "is_live": rows.get("is_live", "1" if url else "0") == "1",
    }

@app.get("/api/stream/audio")
async def stream_audio_proxy():
    stream = get_stream()
    url = stream.get("url")
    if not url:
        raise HTTPException(404, "Stream offline")

    async def audio_chunks():
        async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
            async with client.stream(
                "GET",
                url,
                headers={"User-Agent": "RedNews/1.0", "Icy-MetaData": "0"},
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    yield chunk

    return StreamingResponse(
        audio_chunks(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )

@app.get("/api/status")
def api_status():
    backend = db_backend()
    comments_proxy = should_proxy_comments()
    return {
        "ok": True,
        "database": backend,
        "comments_backend": "proxy" if comments_proxy else backend,
        "persistent_comments": backend == "postgres" or comments_proxy,
    }

class StreamPublish(BaseModel):
    password: str
    url: str
    is_live: bool = True

@app.post("/api/stream/publish")
def publish_stream(data: StreamPublish):
    require_admin_enabled()
    if not _check_password(data.password):
        raise HTTPException(401, "Senha incorreta")
    conn = get_db(); cur = conn.cursor()
    db_execute(cur, "INSERT INTO settings (key,value) VALUES ('stream_url',%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (data.url,))
    db_execute(cur, "INSERT INTO settings (key,value) VALUES ('is_live',%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", ("1" if data.is_live else "0",))
    conn.commit(); cur.close(); conn.close()
    return {"ok": True, "url": data.url}

@app.put("/api/stream")
def update_stream(data: StreamUpdate, token: str = Depends(verify_token)):
    conn = get_db(); cur = conn.cursor()
    if data.url is not None:
        db_execute(cur, "INSERT INTO settings (key,value) VALUES ('stream_url',%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (data.url,))
    if data.is_live is not None:
        db_execute(cur, "INSERT INTO settings (key,value) VALUES ('is_live',%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", ("1" if data.is_live else "0",))
    conn.commit(); cur.close(); conn.close()
    return {"ok": True}

# ── Weather & Rates ───────────────────────────────────────────────────────────

_weather_cache = {"data": None, "ts": 0}
_rates_cache   = {"data": None, "ts": 0}
CACHE_TTL = 600

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
    if code in (0, 1):       return "☀️"
    if code in (2, 3):       return "⛅"
    if code in (45, 48):     return "🌫️"
    if 51 <= code <= 55:     return "🌦️"
    if 61 <= code <= 65:     return "🌧️"
    if 71 <= code <= 75:     return "❄️"
    if 80 <= code <= 82:     return "🌧️"
    if code >= 95:           return "⛈️"
    return "🌡️"

def road_condition(code, wind):
    if code >= 95:       return "⛔", "Risco alto — evite sair"
    if code >= 80:       return "🔴", "Pista alagada — cuidado"
    if code >= 61:       return "🟡", "Pista molhada"
    if code in (45,48):  return "🟠", "Visibilidade reduzida"
    if wind > 50:        return "🟡", "Vento forte"
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
                params={"latitude":35.37,"longitude":-119.02,
                        "current":"temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m",
                        "timezone":"America/Los_Angeles"}
            )
            raw = r.json()
        c = raw["current"]; code = c["weather_code"]; wind = c["wind_speed_10m"]
        rd_icon, rd_text = road_condition(code, wind)
        data = {"temp":round(c["temperature_2m"]),"humidity":c["relative_humidity_2m"],
                "wind":round(wind),"code":code,"description":WMO_DESC.get(code,"—"),
                "icon":wmo_icon(code),"road_icon":rd_icon,"road_text":rd_text}
        _weather_cache["data"] = data; _weather_cache["ts"] = now
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
        usd = raw["USDBRL"]; eur = raw["EURBRL"]
        data = {"usd":{"rate":float(usd["bid"]),"change":float(usd["pctChange"])},
                "eur":{"rate":float(eur["bid"]),"change":float(eur["pctChange"])}}
        _rates_cache["data"] = data; _rates_cache["ts"] = now
        return data
    except Exception:
        return {"usd":{"rate":0,"change":0},"eur":{"rate":0,"change":0}}

# ── Ticker endpoint ───────────────────────────────────────────────────────────

@app.get("/api/ticker")
def get_ticker():
    conn = get_db(); cur = conn.cursor()
    db_execute(cur, "SELECT key,value FROM settings WHERE key IN ('ticker_text','ticker_custom')")
    rows = {r["key"]: r["value"] for r in cur.fetchall()}
    cur.close(); conn.close()
    return {"text": rows.get("ticker_text",""), "use_custom": rows.get("ticker_custom") == "1"}

@app.put("/api/ticker")
def update_ticker(data: TickerUpdate, token: str = Depends(verify_token)):
    conn = get_db(); cur = conn.cursor()
    if data.text is not None:
        db_execute(cur, "INSERT INTO settings (key,value) VALUES ('ticker_text',%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (data.text,))
    if data.use_custom is not None:
        db_execute(cur, "INSERT INTO settings (key,value) VALUES ('ticker_custom',%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", ("1" if data.use_custom else "0",))
    conn.commit(); cur.close(); conn.close()
    return {"ok": True}

# ── Comments endpoints ────────────────────────────────────────────────────────

@app.get("/api/comments/{article_id}")
def get_comments(article_id: str):
    if should_proxy_comments():
        return proxy_comment_request("GET", f"/api/comments/{article_id}")
    conn = get_db(); cur = conn.cursor()
    ids = comment_article_ids(article_id)
    placeholders = ",".join(["%s"] * len(ids))
    db_execute(cur, f"SELECT * FROM comments WHERE article_id IN ({placeholders}) ORDER BY created_at DESC", tuple(ids))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]

@app.post("/api/comments/{article_id}")
def add_comment(article_id: str, item: CommentItem):
    if not item.author.strip() or not item.body.strip():
        raise HTTPException(400, "Nome e comentário obrigatórios")
    if should_proxy_comments():
        return proxy_comment_request("POST", f"/api/comments/{article_id}", item.model_dump())
    cid = secrets.token_hex(8)
    article_id = canonical_article_id(article_id)
    parent_id = item.parent_id.strip()[:80] if item.parent_id and item.parent_id.strip() else None
    conn = get_db(); cur = conn.cursor()
    db_execute(cur,
        "INSERT INTO comments (id,article_id,parent_id,author,body,likes,created_at) VALUES (%s,%s,%s,%s,%s,0,%s)",
        (cid, article_id, parent_id, item.author.strip()[:80], item.body.strip()[:2000], int(time.time()))
    )
    conn.commit(); cur.close(); conn.close()
    return {"id": cid}

@app.post("/api/comments/{article_id}/{comment_id}/like")
def like_comment(article_id: str, comment_id: str):
    if should_proxy_comments():
        return proxy_comment_request("POST", f"/api/comments/{article_id}/{comment_id}/like")
    conn = get_db(); cur = conn.cursor()
    ids = comment_article_ids(article_id)
    placeholders = ",".join(["%s"] * len(ids))
    db_execute(cur, f"UPDATE comments SET likes=likes+1 WHERE id=%s AND article_id IN ({placeholders})", (comment_id, *ids))
    conn.commit(); cur.close(); conn.close()
    return {"ok": True}

# ── Sponsors endpoints ────────────────────────────────────────────────────────

@app.get("/api/sponsors")
def get_sponsors():
    conn = get_db(); cur = conn.cursor()
    db_execute(cur, "SELECT * FROM sponsors")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {r["slot"]: dict(r) for r in rows}

@app.put("/api/sponsors/{slot}")
def update_sponsor(slot: str, data: SponsorUpdate, token: str = Depends(verify_token)):
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if fields:
        conn = get_db(); cur = conn.cursor()
        sets = ", ".join(f"{k}=%s" for k in fields)
        db_execute(cur, f"UPDATE sponsors SET {sets} WHERE slot=%s", (*fields.values(), slot))
        conn.commit(); cur.close(); conn.close()
    return {"ok": True}

# ── Upload endpoint ───────────────────────────────────────────────────────────

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_SIZE = 4 * 1024 * 1024  # 4 MB

@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...), token: str = Depends(verify_token)):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, "Formato inválido. Use JPG, PNG, WebP ou GIF.")
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(400, "Imagem muito grande. Máximo 4MB.")
    b64 = base64.b64encode(data).decode()
    data_url = f"data:{file.content_type};base64,{b64}"
    return {"url": data_url}

# ── Static ────────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse("index.html")

app.mount("/assets", StaticFiles(directory="assets"), name="assets")
