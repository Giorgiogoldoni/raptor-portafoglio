#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAPTOR Portafoglio — Sincronizzazione lista da issue GitHub.
Legge l'evento della issue "[SYNC]" aperta dal proprietario (mai dal testo passato alla shell),
valida le righe "SIMBOLO.BORSA;carico;aaaa-mm-gg" e riscrive portafoglio.json.
Lo Storico presente in portafoglio.json resta invariato.
Scrive sempre un messaggio in SYNC_MSG_FILE (usato come commento sulla issue).
Uscita 0 = ok (anche se nessuna differenza), 1 = rifiutata.
"""
import json, os, re, sys

OWNER    = 'Giorgiogoldoni'
PF       = 'portafoglio.json'
UNIVERSE = 'universe.json'
MSG      = os.environ.get('SYNC_MSG_FILE', '/tmp/sync_msg.txt')
MAX_POS  = 500
LINE = re.compile(r'^([A-Z0-9][A-Z0-9\-]{0,14}\.[A-Z]{1,3});(\d+(?:\.\d+)?);(\d{4}-\d{2}-\d{2})?$')

def out(msg, ok):
    with open(MSG, 'w', encoding='utf-8') as f:
        f.write(msg + '\n')
    print(msg)
    sys.exit(0 if ok else 1)

def short(lst, n=25):
    lst = list(lst)
    return ', '.join(lst[:n]) + (f' … (+{len(lst)-n})' if len(lst) > n else '') if lst else '—'

def main():
    with open(os.environ['GITHUB_EVENT_PATH'], encoding='utf-8') as f:
        issue = (json.load(f).get('issue') or {})
    if (issue.get('user') or {}).get('login') != OWNER or not str(issue.get('title', '')).startswith('[SYNC]'):
        out('❌ Issue non valida: autore o titolo non autorizzati. Nessuna modifica.', False)

    body = (issue.get('body') or '').replace('\r', '')
    pos, errori, vuota = {}, [], False
    for n, raw in enumerate(body.split('\n'), 1):
        line = raw.strip()
        if line == 'LISTA VUOTA':
            vuota = True
            continue
        m = LINE.match(line)
        if m:
            c = float(m.group(2))
            if not (0 < c < 1e7):
                errori.append(f'riga {n}: carico fuori range')
                continue
            pos[m.group(1)] = (round(c, 6), m.group(3) or '')   # in caso di doppioni vince l'ultima
        elif ';' in line:
            errori.append(f'riga {n}: formato non valido')
    if errori:
        out('❌ Lista rifiutata, nessuna modifica. ' + '; '.join(errori[:10]), False)
    if not pos and not vuota:
        out('❌ Nessun titolo riconosciuto nel testo della issue. Nessuna modifica.', False)
    if len(pos) > MAX_POS:
        out(f'❌ Troppi titoli ({len(pos)} > {MAX_POS}). Nessuna modifica.', False)

    try:
        with open(PF, encoding='utf-8') as f:
            old = json.load(f)
    except Exception:
        old = {}
    old_pos = {p['yahoo']: p for p in old.get('posizioni', []) if p.get('yahoo')}
    try:
        with open(UNIVERSE, encoding='utf-8') as f:
            uni = {s: n for s, n in json.load(f)}
    except Exception:
        uni = {}

    nuove = []
    for y, (c, d) in pos.items():
        o = old_pos.get(y, {})
        nuove.append({'yahoo': y, 'nome': o.get('nome') or uni.get(y, ''), 'carico': c,
                      'data_acquisto': d or o.get('data_acquisto', '')})

    aggiunti = [y for y in pos if y not in old_pos]
    tolti    = [y for y in old_pos if y not in pos]
    cambiati = [y for y in pos if y in old_pos and abs(float(old_pos[y].get('carico', 0)) - pos[y][0]) > 1e-9]

    if not (aggiunti or tolti or cambiati):
        out(f'ℹ️ Nessuna differenza rispetto a portafoglio.json ({len(pos)} titoli). Niente da aggiornare.', True)

    with open(PF, 'w', encoding='utf-8') as f:
        json.dump({'posizioni': nuove, 'storico': old.get('storico', [])}, f, ensure_ascii=False, indent=1)

    out(f'✅ Lista aggiornata: {len(nuove)} titoli.\n- Aggiunti: {short(aggiunti)}\n- Tolti: {short(tolti)}\n'
        f'- Carico modificato: {short(cambiati)}\n\nPrezzi e segnali dei titoli nuovi arrivano con il fetch che parte ora '
        f'(1-3 minuti, poi qualche minuto per la pubblicazione).', True)

if __name__ == '__main__':
    main()
