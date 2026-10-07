#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAPTOR Portafoglio — Scan Nuove Partenze (email mattutina, lancio manuale)
Legge etf_scores.json generato da 'core' (punteggio, segnale, classe, età del SAR: tutti calcolati
da core a chiusura di giornata) e tiene gli strumenti con un ingresso "fresco".
Regole in regole_nuove_partenze.json (nella root del repo). Con le impostazioni predefinite
devono valere TUTTE insieme:
  1) SAR rialzista da non più di N giorni (dato di core)
  2) AO (EMA3-EMA13 del prezzo medio) in crescita da N barre, calcolato qui su Yahoo
  3) ER (Kaufman) >= soglia, calcolato qui su Yahoo
AO ed ER usano solo barre chiuse, fino allo stesso giorno dei dati di core.
Le regole effettivamente usate vengono scritte in fondo alla mail.
"""

import json, os, sys, time, smtplib, subprocess, urllib.request, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SCORES_URL = 'https://raw.githubusercontent.com/Giorgiogoldoni/core/main/data/etf_scores.json'
RULES_FILE = 'regole_nuove_partenze.json'
PF_FILE    = 'portafoglio.json'

DEFAULT_RULES = {
    "sar_eta_max": 2,              # SAR rialzista da al massimo N giorni
    "richiedi_ao": True,           # AO in crescita
    "ao_barre": 2,                 #   da N barre consecutive
    "richiedi_er": True,           # ER sopra soglia (esclude i laterali)
    "er_finestra": 10,
    "er_min": 0.30,
    "max_risultati": 15,
    "slot_leva": 3,                # slot riservati (quando disponibili)
    "slot_commodity": 3,
    "classi": ["equity", "commodity", "leva_short"],
    "punteggio_min": 0,
    "segnali_ammessi": [],         # vuoto = tutti (BUY, WATCHLIST..., NO TRADE)
    "escludi_nome": ["liquidity", "overnight", "money market"],  # parole da escludere dal nome
    "segna_portafoglio": True,
}


# ───────────────────────── regole ─────────────────────────
def load_rules():
    rules, avvisi = dict(DEFAULT_RULES), []
    if os.path.exists(RULES_FILE):
        try:
            with open(RULES_FILE, encoding='utf-8') as f:
                user = json.load(f)
            for k, v in user.items():
                if k not in DEFAULT_RULES:
                    avvisi.append(f"regola sconosciuta ignorata: {k}")
                elif type(v) is not type(DEFAULT_RULES[k]) and not (isinstance(v, (int, float)) and isinstance(DEFAULT_RULES[k], (int, float)) and not isinstance(v, bool)):
                    avvisi.append(f"valore non valido per {k}: uso {DEFAULT_RULES[k]}")
                else:
                    d = DEFAULT_RULES[k]
                    rules[k] = int(v) if (isinstance(d, int) and not isinstance(d, bool)) else v
        except Exception as e:
            avvisi.append(f"{RULES_FILE} non leggibile ({e}): uso le regole predefinite")
    return rules, avvisi


def descrivi_regole(r, cutoff, stats, avvisi):
    righe = [f"SAR rialzista da ≤{r['sar_eta_max']} giorni (dato core)"]
    righe.append(f"AO in crescita da {r['ao_barre']} barre" if r['richiedi_ao'] else "AO: non richiesto")
    righe.append(f"ER({r['er_finestra']}) ≥ {r['er_min']}" if r['richiedi_er'] else "ER: non richiesto")
    righe.append("classi: " + "/".join(r['classi']))
    if r['punteggio_min']:
        righe.append(f"punteggio ≥ {r['punteggio_min']}")
    righe.append("segnali: " + (", ".join(r['segnali_ammessi']) if r['segnali_ammessi'] else "tutti"))
    if r['escludi_nome']:
        righe.append("esclusi nomi con: " + ", ".join(r['escludi_nome']))
    righe.append(f"massimo {r['max_risultati']} (riservati {r['slot_leva']} a leva e {r['slot_commodity']} a commodity quando disponibili, il resto per punteggio)")
    testo = "Regole usate: " + "; ".join(righe) + "."
    testo += (f" AO ed ER calcolati su barre chiuse fino al {cutoff}." if (r['richiedi_ao'] or r['richiedi_er']) else "")
    testo += f" Sui {stats['sar']} strumenti con SAR fresco: scartati per AO {stats['ao']}, per ER {stats['er']}, non verificabili {stats['nv']}."
    testo += " Punteggio, segnale e classe vengono da core. 📌 = già in portafoglio."
    if avvisi:
        testo += " ⚠️ " + " · ".join(avvisi)
    return testo


# ───────────────────────── dati core ─────────────────────────
def fetch_scores():
    with urllib.request.urlopen(SCORES_URL, timeout=30) as r:
        return json.loads(r.read().decode())


def check_freschezza(scores, max_ore_feriale=36):
    """Dati di core troppo vecchi? Il lunedì margine di +24h (core gira lun-ven)."""
    gen = scores.get('generated_at')
    if not gen:
        return False, None, "⚠️ etf_scores.json non ha il campo generated_at — impossibile verificare l'età dei dati"
    try:
        gen_dt = datetime.datetime.fromisoformat(gen)
        if gen_dt.tzinfo is not None:
            gen_dt = gen_dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        eta_ore = (now_utc - gen_dt).total_seconds() / 3600
    except Exception as e:
        return False, None, f"⚠️ Impossibile interpretare generated_at ('{gen}'): {e}"
    max_ore = max_ore_feriale + 24 if now_utc.weekday() == 0 else max_ore_feriale
    if eta_ore > max_ore:
        return False, eta_ore, (f"⚠️ Dati di core vecchi di {eta_ore:.0f} ore (soglia {max_ore}h) — "
                                 f"il workflow di aggiornamento di core potrebbe essersi fermato")
    return True, eta_ore, None


def data_chiusura_core(scores):
    """Ultimo giorno di borsa incluso nei dati di core: se generati prima delle 16 UTC la seduta
    del giorno non era chiusa, quindi si conta fino al giorno prima."""
    g = datetime.datetime.fromisoformat(scores['generated_at'])
    if g.tzinfo is not None:
        g = g.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return g.date() if g.hour >= 16 else g.date() - datetime.timedelta(days=1)


# ───────────────────────── filtro core ─────────────────────────
def candidati_sar(scores, r):
    out = []
    for i in scores.get('scores', []):
        if not (i.get('sar_is_up') and i.get('sar_age') is not None and i['sar_age'] <= r['sar_eta_max']):
            continue
        if i.get('asset_class') not in r['classi']:
            continue
        if (i.get('score_operativo') or 0) < r['punteggio_min']:
            continue
        if r['segnali_ammessi'] and i.get('signal') not in r['segnali_ammessi']:
            continue
        nome = (i.get('name') or '').lower()
        if any(p.lower() in nome for p in r['escludi_nome']):
            continue
        out.append(i)
    out.sort(key=lambda x: -(x.get('score_operativo') or 0))
    return out


# ───────────────────────── indicatori (stesse definizioni del motore del portafoglio) ─────────────────────────
def ao_fast(high, low):
    """AO veloce = EMA3 - EMA13 del prezzo medio."""
    mid = [(h + l) / 2 for h, l in zip(high, low)]
    def ema(arr, p):
        k = 2 / (p + 1); out = [arr[0]]
        for x in arr[1:]:
            out.append(x * k + out[-1] * (1 - k))
        return out
    e3, e13 = ema(mid, 3), ema(mid, 13)
    return [a - b for a, b in zip(e3, e13)]


def ao_in_crescita(ao, barre):
    if len(ao) < barre + 1:
        return False
    return all(ao[-k] > ao[-k - 1] for k in range(1, barre + 1))


def efficiency_ratio(close, n):
    if len(close) < n + 1:
        return None
    direction = abs(close[-1] - close[-1 - n])
    vol = sum(abs(close[j] - close[j - 1]) for j in range(len(close) - n, len(close)))
    return direction / vol if vol else 0.0


def get_yfinance():
    try:
        import yfinance as yf
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', 'yfinance'])
        import yfinance as yf
    return yf


def indicatori(sym, cutoff, r, yf):
    """Ritorna {'ao_ok', 'er'} su barre chiuse fino a cutoff, oppure None se i dati mancano."""
    try:
        hist = yf.Ticker(sym).history(period='6mo', interval='1d', timeout=20)
        hist = hist.dropna(subset=['High', 'Low', 'Close'])
        hist = hist[[d.date() <= cutoff for d in hist.index]]
        if len(hist) < 30:
            return None
        high, low, close = (hist[c].astype(float).tolist() for c in ('High', 'Low', 'Close'))
        return {'ao_ok': ao_in_crescita(ao_fast(high, low), r['ao_barre']),
                'er': efficiency_ratio(close, r['er_finestra'])}
    except Exception as e:
        print(f"  {sym}: dati Yahoo non disponibili ({e})")
        return None


def verifica(cands, cutoff, r):
    """Applica AO ed ER ai candidati. Ritorna (passano, statistiche)."""
    stats = {'sar': len(cands), 'ao': 0, 'er': 0, 'nv': 0}
    if not (r['richiedi_ao'] or r['richiedi_er']):
        for c in cands:
            c['_ao'], c['_er'] = None, None
        return cands, stats
    yf = get_yfinance()
    passano = []
    for c in cands:
        ind = indicatori(c['ticker_yf'], cutoff, r, yf)
        time.sleep(0.3)
        if ind is None or (r['richiedi_er'] and ind['er'] is None):
            stats['nv'] += 1
            continue
        c['_ao'], c['_er'] = ind['ao_ok'], ind['er']
        if r['richiedi_ao'] and not ind['ao_ok']:
            stats['ao'] += 1
            continue
        if r['richiedi_er'] and ind['er'] < r['er_min']:
            stats['er'] += 1
            continue
        passano.append(c)
    return passano, stats


def seleziona(passano, r):
    leva = [c for c in passano if c.get('asset_class') == 'leva_short'][:r['slot_leva']]
    commodity = [c for c in passano if c.get('asset_class') == 'commodity'][:r['slot_commodity']]
    riservati = {c['ticker_yf'] for c in leva + commodity}
    resto = [c for c in passano if c['ticker_yf'] not in riservati][:max(0, r['max_risultati'] - len(leva) - len(commodity))]
    top = leva + commodity + resto
    top.sort(key=lambda x: -(x.get('score_operativo') or 0))
    return top


def simboli_portafoglio():
    try:
        with open(PF_FILE, encoding='utf-8') as f:
            return {p['yahoo'] for p in json.load(f).get('posizioni', []) if p.get('yahoo')}
    except Exception:
        return set()


# ───────────────────────── email ─────────────────────────
def build_email_html(items, generated_at, testo_regole, in_pf, r):
    tv_map = {'.MI': 'MIL:', '.DE': 'XETR:', '.PA': 'EURONEXT:', '.L': 'LSE:'}
    rows = ''
    for i in items:
        yahoo = i['ticker_yf']
        tv_pref = next((p for s, p in tv_map.items() if yahoo.endswith(s)), 'MIL:')
        tv_url = f"https://www.tradingview.com/chart/?symbol={tv_pref}{yahoo.split('.')[0]}"
        segnale = i.get('signal') or '—'
        seg_color = '#1a7f37' if segnale == 'BUY' else ('#888' if 'NO TRADE' in segnale else '#e67700')
        pin = ' 📌' if (r['segna_portafoglio'] and yahoo in in_pf) else ''
        ao = '—' if i.get('_ao') is None else ('↑' if i['_ao'] else '✗')
        er = '—' if i.get('_er') is None else f"{i['_er']:.2f}"
        adx = '—' if i.get('adx') is None else f"{i['adx']:.0f}"
        rows += f"""<tr>
          <td style="padding:6px 10px;font-family:monospace;font-weight:700">{yahoo}{pin}</td>
          <td style="padding:6px 10px;font-size:12px;color:#444">{(i.get('name') or '')[:40]}</td>
          <td style="padding:6px 10px;font-size:11px;color:#888">{i.get('asset_class','')}</td>
          <td style="padding:6px 10px;font-size:10px;color:{seg_color};font-weight:700">{segnale}</td>
          <td style="padding:6px 10px;text-align:right;font-weight:700">{i.get('score_operativo')}</td>
          <td style="padding:6px 10px;text-align:center">{i.get('sar_age')}g</td>
          <td style="padding:6px 10px;text-align:center">{ao}</td>
          <td style="padding:6px 10px;text-align:right">{er}</td>
          <td style="padding:6px 10px;text-align:right;color:#888">{adx}</td>
          <td style="padding:6px 10px;text-align:right;font-family:monospace">{i.get('close','—')}</td>
          <td style="padding:6px 10px"><a href="{tv_url}" style="color:#1a6fcf">TradingView</a></td>
        </tr>"""

    th = 'padding:6px 10px'
    return f"""<html><body style="font-family:Arial,sans-serif;background:#f6f8fa;padding:20px">
    <div style="max-width:900px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;border:1px solid #e1e4e8">
      <div style="background:#1a1816;color:#fff;padding:16px 20px">
        <h2 style="margin:0;font-size:18px">🟢 Nuove Partenze — {len(items)} strumenti</h2>
        <div style="font-size:11px;opacity:.7">Dati core aggiornati: {generated_at}</div>
      </div>
      <table style="width:100%;border-collapse:collapse">
        <thead><tr style="background:#f6f8fa;font-size:11px;color:#666;text-align:left">
          <th style="{th}">Ticker</th><th style="{th}">Nome</th><th style="{th}">Classe</th><th style="{th}">Segnale core</th>
          <th style="{th};text-align:right">Score</th><th style="{th}">SAR età</th><th style="{th}">AO</th>
          <th style="{th};text-align:right">ER</th><th style="{th};text-align:right">ADX</th>
          <th style="{th};text-align:right">Prezzo</th><th style="{th}">Grafico</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <div style="padding:12px 20px;font-size:10px;color:#999;line-height:1.5">
        {testo_regole}<br>Fonte dati: <a href="https://giorgiogoldoni.github.io/core/">core</a> (non è un consiglio di investimento).
      </div>
    </div>
    </body></html>"""


def build_warning_email_html(msg, eta_ore, generated_at):
    return f"""<html><body style="font-family:Arial,sans-serif;background:#f6f8fa;padding:20px">
    <div style="max-width:600px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;border:1px solid #e1e4e8">
      <div style="background:#862e2e;color:#fff;padding:16px 20px"><h2 style="margin:0;font-size:16px">⚠️ Dati core non aggiornati</h2></div>
      <div style="padding:16px 20px;font-size:13px;color:#333">
        <p>{msg}</p>
        <p style="font-size:11px;color:#888">generated_at riportato: {generated_at or '—'}{f' · età: {eta_ore:.0f}h' if eta_ore is not None else ''}</p>
        <p style="font-size:11px;color:#888">Nessuna scansione "nuove partenze" eseguita oggi — verifica il workflow
        di <a href="https://github.com/Giorgiogoldoni/core/actions">core</a>.</p>
      </div>
    </div></body></html>"""


def send_email(subject, html):
    EMAIL_USER = os.environ.get('EMAIL_USER', '')
    EMAIL_PASS = os.environ.get('EMAIL_PASS', '')
    if not EMAIL_USER or not EMAIL_PASS:
        print("EMAIL non configurata — skip")
        return
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg.attach(MIMEText(html, 'html'))
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as srv:
        srv.login(EMAIL_USER, EMAIL_PASS)
        srv.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
    print(f"✅ Email inviata: {subject}")


def main():
    now = datetime.datetime.now()
    print(f"Scan Nuove Partenze — {now.strftime('%Y-%m-%d %H:%M')}")
    rules, avvisi = load_rules()
    for a in avvisi:
        print("⚠️", a)
    try:
        scores = fetch_scores()
    except Exception as e:
        print(f"❌ Errore lettura etf_scores.json: {e}")
        return

    ok, eta_ore, msg = check_freschezza(scores)
    if not ok:
        print(msg)
        send_email(f"⚠️ RAPTOR — dati core non aggiornati · {now.strftime('%d/%m %H:%M')}",
                   build_warning_email_html(msg, eta_ore, scores.get('generated_at')))
        return
    print(f"✅ Dati core freschi (età: {eta_ore:.1f}h)")

    cutoff = data_chiusura_core(scores)
    cands = candidati_sar(scores, rules)
    print(f"Candidati con SAR fresco e filtri core: {len(cands)}")
    passano, stats = verifica(cands, cutoff, rules)
    top = seleziona(passano, rules)
    print(f"Dopo AO/ER: {len(passano)} · scelti {len(top)} (max {rules['max_risultati']}) · "
          f"scartati AO {stats['ao']}, ER {stats['er']}, non verificabili {stats['nv']}")

    testo = descrivi_regole(rules, cutoff, stats, avvisi)
    in_pf = simboli_portafoglio()
    output = {
        'generated_at': now.isoformat(), 'core_generated_at': scores.get('generated_at'),
        'count': len(top), 'regole': rules, 'statistiche': stats,
        'items': [{
            'ticker': i['ticker_yf'], 'nome': i.get('name', ''), 'asset_class': i.get('asset_class'),
            'score': i.get('score_operativo'), 'sar_age': i.get('sar_age'), 'prezzo': i.get('close'),
            'signal': i.get('signal'), 'ao_ok': i.get('_ao'),
            'er': None if i.get('_er') is None else round(i['_er'], 3),
            'in_portafoglio': i['ticker_yf'] in in_pf,
        } for i in top],
    }
    with open('nuove_partenze.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

    if not top:
        print("Nessuna nuova partenza oggi con queste regole — invio comunque la mail con le regole usate")
    send_email(f"🟢 Nuove Partenze — {len(top) if top else 'nessuna'} {'strumenti ' if top else ''}· {now.strftime('%d/%m')}",
               build_email_html(top, scores.get('generated_at', '—'), testo, in_pf, rules))


if __name__ == '__main__':
    main()
