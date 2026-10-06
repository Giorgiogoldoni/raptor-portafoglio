#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAPTOR Portafoglio — Alert Stop (autonomo)
Gira ogni 30 minuti. Confronta le posizioni di portafoglio.json (chiave: simbolo Yahoo)
con i dati live propri (raptor_portafoglio_live.json, generato da fetch_data.py).
Invia email se:
- Zona USCITA
- P&L <= -10% rispetto al carico (stop loss)
Lo stato anti-duplicati viene salvato solo se l'email parte davvero.
"""

import json, os, sys, smtplib
from datetime import datetime
from zoneinfo import ZoneInfo
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

PF_LOCAL   = 'portafoglio.json'
LIVE_LOCAL = 'raptor_portafoglio_live.json'
STOP_LOSS_PCT = -10.0  # alert se P&L <= -10%

STATE_FILE     = 'alert_state.json'
COOLDOWN_HOURS = 6  # non rimandare lo stesso alert (stessa zona) prima di N ore

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def load_json_local(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def send_alert(subject, html):
    """True se l'email è stata inviata, False se le credenziali mancano. Solleva eccezione se l'invio fallisce."""
    EMAIL_USER = os.environ.get('EMAIL_USER', '')
    EMAIL_PASS = os.environ.get('EMAIL_PASS', '')
    if not EMAIL_USER or not EMAIL_PASS:
        print("EMAIL non configurata — skip")
        return False
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = EMAIL_USER
    msg['To']      = EMAIL_USER
    msg.attach(MIMEText(html, 'html'))
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as srv:
        srv.login(EMAIL_USER, EMAIL_PASS)
        srv.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
    print(f"✅ Alert inviato: {subject}")
    return True

def build_alert_html(alerts, now):
    th = 'padding:6px 12px;text-align:left;border-bottom:2px solid #e0ddd6'
    rows = ''
    for a in alerts:
        zona_color = {'USCITA': '#c92a2a'}.get(a['zona'], '#e67700')
        pl_color   = '#c92a2a' if a['pl_pct'] < 0 else '#2f9e44'
        rows += f"""<tr style="background:#fff8f8;border-bottom:1px solid #f5e0e0">
          <td style="padding:8px 12px;font-weight:700;font-family:monospace">{a['ticker']}</td>
          <td style="padding:8px 12px;font-size:11px;color:#57606a">{a['nome']}</td>
          <td style="padding:8px 12px;font-family:monospace">{a['carico']:.4f}</td>
          <td style="padding:8px 12px;font-family:monospace;font-weight:700">{a['prezzo']:.4f}</td>
          <td style="padding:8px 12px;text-align:center">
            <span style="background:{zona_color};color:#fff;padding:2px 8px;border-radius:3px;font-size:10px;font-weight:700">{a['zona']}</span>
          </td>
          <td style="padding:8px 12px;font-family:monospace;color:{pl_color};font-weight:700">
            {'+' if a['pl_pct']>=0 else ''}{a['pl_pct']:.2f}%
          </td>
          <td style="padding:8px 12px;font-size:11px;color:#c92a2a;font-weight:700">{a['motivo']}</td>
        </tr>"""

    return f"""<!DOCTYPE html><html><body style="font-family:'Segoe UI',sans-serif;background:#f5f4f0;padding:20px;margin:0">
<div style="max-width:720px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.08)">
  <div style="background:#c92a2a;color:#fff;padding:16px 22px">
    <h2 style="margin:0;font-size:19px">⚠️ RAPTOR Portafoglio — Alert Stop</h2>
    <p style="margin:5px 0 0;font-size:11px;opacity:.85">{now.strftime('%d/%m/%Y %H:%M')} · {len(alerts)} posizione/i da verificare</p>
  </div>
  <div style="padding:18px 22px">
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead><tr style="background:#f5f4f0">
        <th style="{th}">Ticker</th><th style="{th}">Nome</th><th style="{th}">Carico</th>
        <th style="{th}">Prezzo</th><th style="{th}">Zona</th><th style="{th}">P&L</th><th style="{th}">Motivo Alert</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <p style="margin-top:16px;padding-top:12px;border-top:1px solid #e0ddd6;font-size:11px;color:#7a766e">
      📋 <a href="https://giorgiogoldoni.github.io/raptor-portafoglio/portafoglio.html" style="color:#1a6fcf">Apri Portafoglio</a>
      &nbsp;·&nbsp; ⚠️ Solo uso educativo
    </p>
  </div>
</div></body></html>"""

def main():
    # ora italiana, senza fuso (compatibile con le date già salvate in alert_state.json)
    now = datetime.now(ZoneInfo('Europe/Rome')).replace(tzinfo=None)
    print(f"RAPTOR Alert Check — {now.strftime('%Y-%m-%d %H:%M')}")

    try:
        pf   = load_json_local(PF_LOCAL)
        live_data = load_json_local(LIVE_LOCAL)
    except FileNotFoundError as e:
        print(f"❌ File dati non trovato (fetch_data.py non ha generato output?): {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Errore lettura dati locali: {e}")
        sys.exit(1)

    live_map = {d['yahoo']: d for d in live_data.get('data', []) if d.get('yahoo')}
    posizioni = pf.get('posizioni', [])
    print(f"Posizioni in portafoglio: {len(posizioni)}")

    alerts = []
    for pos in posizioni:
        y = pos.get('yahoo')
        if not y:
            print(f"  riga senza simbolo yahoo, salto: {pos}")
            continue
        ticker = y.split('.')[0]
        live   = live_map.get(y)
        if not live:
            print(f"  {y}: nessun dato in raptor_portafoglio_live.json — salto")
            continue

        carico = pos.get('carico')
        prezzo = live.get('prezzo')
        if not carico or carico <= 0 or prezzo is None:
            print(f"  {y}: carico o prezzo mancante — salto")
            continue

        zona   = live.get('zona', '—')
        nome   = pos.get('nome') or live.get('nome', ticker)
        pl_pct = (prezzo - carico) / carico * 100

        motivi = []
        if zona == 'USCITA':
            motivi.append('🔴 SEGNALE USCITA — SAR ribassista o incrocio RSI negativo')
        if pl_pct <= STOP_LOSS_PCT:
            motivi.append(f'📉 Stop loss {pl_pct:.1f}%')

        print(f"  {y}: zona={zona} P&L={pl_pct:.2f}% {'⚠️ ALERT' if motivi else 'OK'}")

        if motivi:
            alerts.append({
                'yahoo': y, 'ticker': ticker, 'nome': nome,
                'carico': carico, 'prezzo': prezzo,
                'zona': zona, 'pl_pct': pl_pct,
                'motivo': ' · '.join(motivi)
            })

    # --- Deduplica per stato + cooldown (chiave = simbolo Yahoo) ---
    state = load_state()
    to_send = []
    new_entries = {}   # stato da salvare solo se l'email parte
    active = set()

    for a in alerts:
        y = a['yahoo']
        active.add(y)
        prev = state.get(y)

        if prev is None or prev.get('zona') != a['zona']:
            to_send.append(a)
            new_entries[y] = {'zona': a['zona'], 'last_sent': now.isoformat()}
            print(f"  {y}: nuovo evento/cambio zona -> invio")
        else:
            last_sent = datetime.fromisoformat(prev['last_sent'])
            elapsed_h = (now - last_sent).total_seconds() / 3600
            if elapsed_h >= COOLDOWN_HOURS:
                to_send.append(a)
                new_entries[y] = {'zona': a['zona'], 'last_sent': now.isoformat()}
                print(f"  {y}: stessa zona ma cooldown scaduto ({elapsed_h:.1f}h) -> reminder")
            else:
                print(f"  {y}: stessa zona, cooldown attivo ({elapsed_h:.1f}h/{COOLDOWN_HOURS}h) -> skip")

    # rimuovi dallo stato i simboli rientrati in zona sicura (o usciti dalla lista)
    for y in list(state.keys()):
        if y not in active:
            print(f"  {y}: rientrato in zona sicura -> reset stato")
            del state[y]

    if to_send:
        n_uscita = sum(1 for a in to_send if 'USCITA' in a['motivo'])
        subj = f"⚠️ RAPTOR Alert — {len(to_send)} posizioni · {now.strftime('%d/%m %H:%M')}"
        if n_uscita:
            subj = f"🔴 RAPTOR Alert — {n_uscita} USCITA · {now.strftime('%d/%m %H:%M')}"
        try:
            if send_alert(subj, build_alert_html(to_send, now)):
                state.update(new_entries)   # segna come notificati solo dopo l'invio riuscito
        except Exception as e:
            # l'errore non deve bloccare la pubblicazione dei dati: lo stato resta invariato, si riprova al giro dopo
            print(f"❌ Invio email fallito: {e}")
    elif alerts:
        print("✅ Alert attivi ma già notificati di recente (dedup/cooldown) — nessuna nuova email")
    else:
        print("✅ Nessun alert — tutte le posizioni in zona sicura")

    save_state(state)

if __name__ == '__main__':
    main()
