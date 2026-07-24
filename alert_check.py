#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAPTOR Portafoglio — Alert Stop
Gira ogni 30 minuti. Confronta posizioni in portafoglio.json
con i dati live di raptor_leva.json. Invia email se:
- Zona → USCITA o STOP
- P&L < -10% (stop loss automatico)
"""

import json, os, sys, smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import urllib.request

LEVA_URL = 'https://raw.githubusercontent.com/Giorgiogoldoni/raptor-leva/main/raptor_leva.json'
PF_URL   = 'https://raw.githubusercontent.com/Giorgiogoldoni/raptor-portafoglio/main/portafoglio.json'
STOP_LOSS_PCT = -10.0  # alert se P&L < -10%

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

def fetch_json(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read().decode())

def send_alert(subject, html):
    EMAIL_USER = os.environ.get('EMAIL_USER', '')
    EMAIL_PASS = os.environ.get('EMAIL_PASS', '')
    if not EMAIL_USER or not EMAIL_PASS:
        print("EMAIL non configurata — skip")
        return
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = EMAIL_USER
    msg['To']      = EMAIL_USER
    msg.attach(MIMEText(html, 'html'))
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as srv:
        srv.login(EMAIL_USER, EMAIL_PASS)
        srv.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
    print(f"✅ Alert inviato: {subject}")

def build_alert_html(alerts, now):
    rows = ''
    for a in alerts:
        zona_color = {'USCITA': '#c92a2a', 'STOP': '#862e2e'}.get(a['zona'], '#e67700')
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
            ({'+' if a['pl_eur']>=0 else ''}{a['pl_eur']:.0f}€)
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
        <th style="padding:6px 12px;text-align:left;border-bottom:2px solid #e0ddd6">Ticker</th>
        <th style="padding:6px 12px;text-align:left;border-bottom:2px solid #e0ddd6">Nome</th>
        <th style="padding:6px 12px;text-align:left;border-bottom:2px solid #e0ddd6">Carico</th>
        <th style="padding:6px 12px;text-align:left;border-bottom:2px solid #e0ddd6">Prezzo</th>
        <th style="padding:6px 12px;text-align:left;border-bottom:2px solid #e0ddd6">Zona</th>
        <th style="padding:6px 12px;text-align:left;border-bottom:2px solid #e0ddd6">P&L</th>
        <th style="padding:6px 12px;text-align:left;border-bottom:2px solid #e0ddd6">Motivo Alert</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <p style="margin-top:16px;padding-top:12px;border-top:1px solid #e0ddd6;font-size:11px;color:#7a766e">
      📋 <a href="https://giorgiogoldoni.github.io/raptor-portafoglio/" style="color:#1a6fcf">Apri Portafoglio</a>
      &nbsp;·&nbsp; ⚡ <a href="https://giorgiogoldoni.github.io/raptor-leva/RAPTOR_Leva.html" style="color:#1a6fcf">Apri RAPTOR Leva</a>
      &nbsp;·&nbsp; ⚠️ Solo uso educativo
    </p>
  </div>
</div></body></html>"""

def main():
    now = datetime.now()
    print(f"RAPTOR Alert Check — {now.strftime('%Y-%m-%d %H:%M')}")

    try:
        pf   = fetch_json(PF_URL)
        leva = fetch_json(LEVA_URL)
    except Exception as e:
        print(f"❌ Errore fetch dati: {e}")
        sys.exit(1)

    leva_map = {d['ticker']: d for d in leva.get('data', [])}
    posizioni = pf.get('posizioni', [])
    print(f"Posizioni in portafoglio: {len(posizioni)}")

    alerts = []
    for pos in posizioni:
        ticker = pos['ticker']
        live   = leva_map.get(ticker)
        if not live:
            print(f"  {ticker}: non trovato in raptor_leva.json")
            continue

        carico = pos['carico']
        prezzo = live.get('prezzo', carico)
        zona   = live.get('zona', '—')
        nome   = pos.get('nome') or live.get('nome', ticker)
        pl_pct = (prezzo - carico) / carico * 100
        pl_eur = (prezzo - carico) * pos.get('quantita', 0)

        motivi = []
        if zona == 'STOP':
            motivi.append('⛔ ZONA STOP — uscita immediata')
        elif zona == 'USCITA':
            motivi.append('🔴 ZONA USCITA — valutare uscita')
        if pl_pct <= STOP_LOSS_PCT:
            motivi.append(f'📉 Stop loss -{abs(pl_pct):.1f}%')

        print(f"  {ticker}: zona={zona} P&L={pl_pct:.2f}% {'⚠️ ALERT' if motivi else 'OK'}")

        if motivi:
            alerts.append({
                'ticker': ticker, 'nome': nome,
                'carico': carico, 'prezzo': prezzo,
                'zona': zona, 'pl_pct': pl_pct, 'pl_eur': pl_eur,
                'motivo': ' · '.join(motivi)
            })

    # --- Deduplica per stato + cooldown ---
    state = load_state()
    to_send = []
    active_tickers = set()

    for a in alerts:
        ticker = a['ticker']
        active_tickers.add(ticker)
        prev = state.get(ticker)

        if prev is None or prev.get('zona') != a['zona']:
            # nuovo evento o cambio di zona -> invia sempre
            to_send.append(a)
            state[ticker] = {'zona': a['zona'], 'last_sent': now.isoformat()}
            print(f"  {ticker}: nuovo evento/cambio zona -> invio")
        else:
            last_sent = datetime.fromisoformat(prev['last_sent'])
            elapsed_h = (now - last_sent).total_seconds() / 3600
            if elapsed_h >= COOLDOWN_HOURS:
                to_send.append(a)
                state[ticker]['last_sent'] = now.isoformat()
                print(f"  {ticker}: stessa zona ma cooldown scaduto ({elapsed_h:.1f}h) -> reminder")
            else:
                print(f"  {ticker}: stessa zona, cooldown attivo ({elapsed_h:.1f}h/{COOLDOWN_HOURS}h) -> skip")

    # rimuovi dallo stato i ticker rientrati in zona sicura
    for ticker in list(state.keys()):
        if ticker not in active_tickers:
            print(f"  {ticker}: rientrato in zona sicura -> reset stato")
            del state[ticker]

    save_state(state)

    if to_send:
        n_stop = sum(1 for a in to_send if 'STOP' in a['motivo'])
        subj   = f"⚠️ RAPTOR Alert — {len(to_send)} posizioni · {now.strftime('%d/%m %H:%M')}"
        if n_stop:
            subj = f"⛔ STOP! RAPTOR Alert — {n_stop} STOP · {now.strftime('%d/%m %H:%M')}"
        html = build_alert_html(to_send, now)
        send_alert(subj, html)
    elif alerts:
        print("✅ Alert attivi ma già notificati di recente (dedup/cooldown) — nessuna nuova email")
    else:
        print("✅ Nessun alert — tutte le posizioni in zona sicura")

if __name__ == '__main__':
    main()
