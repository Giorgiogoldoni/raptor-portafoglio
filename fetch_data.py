#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAPTOR Portafoglio — Fetch autonomo (motore adattato da raptor-leva)
Scarica storico 2 anni per i 45 ETF/ETP tracciati (il BTP JA64YQ è
escluso: nessun dato affidabile via yfinance per obbligazioni MOT).
Calcola doppia KAMA (veloce=entrata, lenta=uscita), SAR, AO veloce,
RSI/RSI5, baffetti, zona operativa e segnale — stesso motore di
raptor-leva. Genera:
  - raptor_portafoglio_live.json  (stato live per portafoglio.html / alert_check.py)
  - data/charts/TICKER.json       (storico 2y + indicatori giornalieri
                                    precalcolati, formato scannerv3 per
                                    chart_widget.js)
  - data/charts/index.json        (indice ticker -> file, per il widget)
Gira ogni 30 min, 6-18 UTC, lun-ven (vedi .github/workflows/fetch.yml).
"""

import json, time, datetime, math
import yfinance as yf

def sf(x):
    """Sanifica un valore numerico per il JSON: NaN/Infinity -> None (mai NaN letterale in output)."""
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(xf) or math.isinf(xf)) else xf

# ═══════════════════════════════════════════════════════
# UNIVERSO — 45 ETF/ETP del portafoglio reale (BTP escluso)
# ═══════════════════════════════════════════════════════
TICKERS = [
  {"t":"LCOP","y":"LCOP.MI","n":"WisdomTree Copper 2x Daily Leveraged"},
  {"t":"LCOC","y":"LCOC.MI","n":"WisdomTree Cocoa 2x Daily Leveraged"},
  {"t":"BAYN","y":"BAYN.DE","n":"Bayer AG"},
  {"t":"3OIS","y":"3SOI.DE","n":"WisdomTree WTI Crude Oil 3x Short"},
  {"t":"3LM","y":"3LMS.MI","n":"WisdomTree Microsoft 3x Daily Leveraged"},
  {"t":"3WHL","y":"3WHL.MI","n":"WisdomTree Wheat 3x Daily Leveraged"},
  {"t":"2PAL","y":"2PAL.MI","n":"WisdomTree Palladium 2x Daily Leveraged"},
  {"t":"EXUS","y":"EXUS.MI","n":"Xtrackers MSCI World ex USA UCITS ETF 1C"},
  {"t":"NCLR","y":"NCLR.MI","n":"WisdomTree Uranium and Nuclear Energy UCITS ETF Acc"},
  {"t":"CSPXJ","y":"CSPXJ.MI","n":"iShares Core MSCI Pacific ex-Japan UCITS ETF USD (Acc)"},
  {"t":"SEMA","y":"SEMA.MI","n":"iShares MSCI EM UCITS ETF USD (Acc)"},
  {"t":"XZEM","y":"XZEM.MI","n":"Xtrackers MSCI Emerging Markets ESG UCITS ETF 1 C"},
  {"t":"WRNW","y":"WRNW.MI","n":"WisdomTree Renewable Energy UCITS ETF Acc"},
  {"t":"DFND","y":"DFND.MI","n":"iShares Global Aerospace & Defence UCITS ETF USD (Acc)"},
  {"t":"SAUDI","y":"SAUDI.MI","n":"Franklin FTSE Saudi Arabia UCITS ETF Acc"},
  {"t":"FLXT","y":"FLXT.MI","n":"Franklin FTSE Taiwan UCITS ETF"},
  {"t":"SEML","y":"SEML.MI","n":"iShares J.P. Morgan EM Local Govt Bond UCITS ETF USD (Dist)"},
  {"t":"VUKE","y":"VUKE.MI","n":"Vanguard FTSE 100 UCITS ETF (GBP) Dis"},
  {"t":"HSTE","y":"HSTE.MI","n":"HSBC Hang Seng Tech UCITS ETF"},
  {"t":"XWTS","y":"XWTS.MI","n":"Xtrackers MSCI World Communication Services UCITS ETF"},
  {"t":"IWMO","y":"IWMO.MI","n":"iShares Edge MSCI World Momentum Factor UCITS ETF USD (Acc)"},
  {"t":"IEMO","y":"IEMO.MI","n":"iShares Edge MSCI Europe Momentum Factor UCITS ETF EUR (Acc)"},
  {"t":"MEUD","y":"MEUD.MI","n":"Amundi IS Core Stoxx Europe 600 UCITS ETF Acc"},
  {"t":"INDO","y":"INDO.MI","n":"Amundi MSCI Indonesia UCITS ETF Acc"},
  {"t":"XEON","y":"XEON.MI","n":"Xtrackers II EUR Overnight Rate Swap UCITS ETF 1C"},
  {"t":"XFVT","y":"XFVT.MI","n":"Xtrackers Vietnam Swap UCITS ETF 1C"},
  {"t":"QDVA","y":"QDVA.DE","n":"iShares Edge MSCI USA Momentum Factor UCITS ETF USD (Acc)"},
  {"t":"XESD","y":"XESD.DE","n":"Xtrackers Spain UCITS ETF 1D"},
  {"t":"D5BI","y":"D5BI.DE","n":"Xtrackers MSCI Mexico UCITS ETF 1C"},
  {"t":"ISPY","y":"ISPY.MI","n":"L&G Cyber Security UCITS ETF"},
  {"t":"INDI","y":"INDI.MI","n":"Amundi MSCI India Swap UCITS ETF EUR Acc"},
  {"t":"STHE","y":"STHE.MI","n":"PIMCO Advantage US Short-Term HY Corporate Bond UCITS ETF EUR Hdg Inc"},
  {"t":"AIAI","y":"AIAI.MI","n":"L&G Artificial Intelligence UCITS ETF"},
  {"t":"GLUG","y":"GLUG.MI","n":"L&G Clean Water UCITS ETF"},
  {"t":"LGGL","y":"LGGL.MI","n":"L&G Global Equity UCITS ETF $"},
  {"t":"SP1E","y":"SP1E.MI","n":"L&G S&P 100 Equal Weight UCITS ETF"},
  {"t":"XS7W","y":"XS7W.MI","n":"Xtrackers Portfolio Income UCITS ETF 1D"},
  {"t":"GERD","y":"GERD.MI","n":"L&G Gerd Kommer Multifactor Equity UCITS ETF Acc"},
  {"t":"LTAM","y":"LTAM.MI","n":"iShares MSCI EM Lat America UCITS ETF USD (Dist)"},
  {"t":"LABL","y":"LABL.MI","n":"L&G Global Brands UCITS ETF Acc"},
  {"t":"BATT","y":"BATT.MI","n":"L&G Battery Value-Chain UCITS ETF"},
  {"t":"SUSW","y":"SUSW.MI","n":"iShares MSCI World SRI UCITS ETF EUR (Acc)"},
  {"t":"EUNY","y":"EUNY.DE","n":"iShares EM Dividend UCITS ETF USD (Dist)"},
  {"t":"LYXLVE","y":"DJLEV.MI","n":"Amundi EURO STOXX 50 Daily (2X) Leveraged UCITS ETF"},
  {"t":"SDGPEX","y":"ISPA.F","n":"iShares STOXX Gl.Select Dividend 100 UCITS ETF(DE)"},
]

VIX_TICKERS = [
    {"t": "VIX_USA", "y": "^VIX"},
    # VSTOXX (^V2TX) non è disponibile su Yahoo Finance (mai stato, non solo delisted) — regime calcolato solo su VIX
]

CHARTS_DIR = 'data/charts'

# ═══════════════════════════════════════════════════════
# INDICATORI (identici a raptor-leva)
# ═══════════════════════════════════════════════════════

def calc_kama(close, n=10, fast=2, slow=30):
    fast_sc = 2/(fast+1); slow_sc = 2/(slow+1)
    kama = [None]*len(close)
    if len(close) <= n: return kama
    kama[n] = close[n]
    for i in range(n+1, len(close)):
        direction = abs(close[i] - close[i-n])
        volatility = sum(abs(close[j]-close[j-1]) for j in range(i-n+1,i+1))
        er = direction/volatility if volatility else 0
        sc = (er*(fast_sc-slow_sc)+slow_sc)**2
        kama[i] = kama[i-1] + sc*(close[i]-kama[i-1])
    return kama

def calc_ao_fast_arr(high, low):
    """AO veloce EMA3-EMA13 come array (per storico/segnali giorno per giorno)."""
    mid = [(h+l)/2 for h,l in zip(high,low)]
    def ema_arr(arr, p):
        k = 2/(p+1); out = [arr[0]]
        for x in arr[1:]: out.append(x*k + out[-1]*(1-k))
        return out
    if len(mid) < 13: return [0]*len(mid)
    e3 = ema_arr(mid, 3); e13 = ema_arr(mid, 13)
    return [round(a-b,4) for a,b in zip(e3,e13)]

def calc_rsi_arr(close, n=14):
    out = [None]*len(close)
    if len(close) < n+1: return out
    gains=[0.0]; losses=[0.0]
    for i in range(1,len(close)):
        d = close[i]-close[i-1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    for i in range(n, len(close)):
        ag = sum(gains[i-n+1:i+1])/n; al = sum(losses[i-n+1:i+1])/n
        out[i] = 100 if al==0 else round(100-100/(1+ag/al),2)
    return out

def calc_baff_arr(high, low):
    mid = [(h+l)/2 for h,l in zip(high,low)]
    out = [0]*len(mid)
    for i in range(1,len(mid)):
        out[i] = out[i-1]+1 if mid[i] > mid[i-1] else 0
    return out

def calc_er_arr(close, n=10):
    out = [0]*len(close)
    for i in range(n, len(close)):
        direction = abs(close[i]-close[i-n])
        vol = sum(abs(close[j]-close[j-1]) for j in range(i-n+1,i+1))
        out[i] = round(direction/vol,4) if vol else 0
    return out

def calc_sar_arr(high, low, step=0.03, max_af=0.25):
    if len(high) < 5: return [None]*len(high), [True]*len(high)
    sar = [None]*len(high); bull_arr=[True]*len(high)
    bull = high[1] > high[0]
    af = step
    ep = max(high[:2]) if bull else min(low[:2])
    sar[1] = min(low[:2]) if bull else max(high[:2])
    bull_arr[1] = bull
    for i in range(2, len(high)):
        prev_sar = sar[i-1]
        if bull:
            sar[i] = prev_sar + af*(ep-prev_sar)
            sar[i] = min(sar[i], low[i-1], low[i-2] if i>=2 else low[i-1])
            if low[i] < sar[i]:
                bull=False; af=step; sar[i]=ep; ep=low[i]
            else:
                if high[i] > ep: ep=high[i]; af=min(af+step,max_af)
        else:
            sar[i] = prev_sar + af*(ep-prev_sar)
            sar[i] = max(sar[i], high[i-1], high[i-2] if i>=2 else high[i-1])
            if high[i] > sar[i]:
                bull=True; af=step; sar[i]=ep; ep=high[i]
            else:
                if low[i] < ep: ep=low[i]; af=min(af+step,max_af)
        bull_arr[i] = bull
    return sar, bull_arr

def get_zona(price, kf, ks):
    if kf is None or ks is None: return 'ND'
    if price > kf and kf > ks: return 'LONG_CONF'
    elif price > kf and price > ks: return 'LONG_EARLY'
    elif price > ks and price < kf: return 'GRIGIA'
    elif price < ks:
        gap = (ks-price)/ks*100 if ks>0 else 0
        return 'STOP' if gap > 2 else 'USCITA'
    return 'GRIGIA'

VOL_MIN_CONF, VOL_MIN_EARLY = 2.0, 1.5
BAF_MIN_CONF, BAF_MIN_EARLY = 3, 3
ER_MIN, KAMA_GAP_MIN = 0.35, 0.003
SCORE_MIN = 65
VIX_BLOCK, VIX_ONLY_CONF = 28, 22

def get_regime_vix(vix, vstoxx):
    if vix is None and vstoxx is None:
        avg = 20  # nessun dato disponibile, fallback neutro
    elif vstoxx is None:
        avg = vix  # solo VIX disponibile (caso normale: VSTOXX non è su Yahoo)
    else:
        avg = (vix + vstoxx) / 2
    if avg < 15: return {'regime':'CALMA','mult':1.00}
    if avg < 20: return {'regime':'NORMALE','mult':0.95}
    if avg < 25: return {'regime':'ATTENZIONE','mult':0.85}
    if avg < 30: return {'regime':'STRESS','mult':0.70}
    return {'regime':'PAURA','mult':0.50}

def get_segnale(zona, ao, vol_ratio, er, baf, kf, ks, regime, sar_bull):
    if regime in ('STRESS','PAURA'):
        if zona=='STOP': return 'STOP'
        if zona=='USCITA': return 'USCITA'
        return ''
    kama_gap_ok = True
    if kf and ks and ks>0:
        kama_gap_ok = abs(kf-ks)/ks >= KAMA_GAP_MIN
    if zona=='LONG_CONF' and ao>0 and vol_ratio>=VOL_MIN_CONF and baf>=BAF_MIN_CONF and er>=ER_MIN and kama_gap_ok and sar_bull:
        return 'LONG'
    elif zona=='LONG_EARLY' and ao>0 and vol_ratio>=VOL_MIN_EARLY and baf>=BAF_MIN_EARLY and er>=ER_MIN and kama_gap_ok and regime!='ATTENZIONE':
        return 'EARLY'
    elif zona in ('LONG_CONF','LONG_EARLY'):
        return 'WATCH'
    elif zona=='STOP': return 'STOP'
    elif zona=='USCITA': return 'USCITA'
    elif zona=='GRIGIA': return 'ATTENZIONE'
    return ''

def calc_score(zona, ao, vol_ratio, er, baf, regime_mult):
    base = 0
    if zona=='LONG_CONF': base=60
    elif zona=='LONG_EARLY': base=40
    elif zona=='GRIGIA': base=20
    base += min(baf,5)*6
    base += (10 if ao>0 else 0)
    base += min(vol_ratio,3)*5
    base += er*20
    return round(base*regime_mult,1)

def calc_vol_ratio_arr(volume):
    out=[1.0]*len(volume)
    for i in range(20,len(volume)):
        avg = sum(volume[i-20:i])/20
        out[i] = round(volume[i]/avg,2) if avg>0 else 1.0
    return out

def fetch_vix():
    vix_val=None; vstoxx_val=None
    for v in VIX_TICKERS:
        try:
            tk = yf.Ticker(v['y'])
            hist = tk.history(period='5d', interval='1d', timeout=15)
            if not hist.empty:
                val = float(hist['Close'].iloc[-1])
                if v['t']=='VIX_USA': vix_val = round(val,2)
                elif v['t']=='VSTOXX_EU': vstoxx_val = round(val,2)
        except Exception as e:
            print(f"Errore fetch VIX {v['t']}: {e}")
        time.sleep(0.5)
    return vix_val, vstoxx_val

# ═══════════════════════════════════════════════════════
# PROCESS TICKER — 2 anni, indicatori completi giorno per giorno
# ═══════════════════════════════════════════════════════
def process_ticker(info, regime_mult, regime_name):
    symbol = info['y']
    try:
        tk = yf.Ticker(symbol)
        hist = tk.history(period='2y', interval='1d', timeout=20)
        hist = hist.dropna(subset=['Open','High','Low','Close'])  # elimina barre incomplete (festivi/dati mancanti)
        if hist.empty or len(hist) < 60:
            print(f"  {info['t']}: storico insufficiente ({len(hist)} barre)")
            return None, None

        close  = [float(x) for x in hist['Close'].values]
        high   = [float(x) for x in hist['High'].values]
        low    = [float(x) for x in hist['Low'].values]
        openp  = [float(x) for x in hist['Open'].values]
        volume = [float(x) for x in hist['Volume'].values]
        ts     = [int(t.timestamp()) for t in hist.index]

        kama_fast = calc_kama(close, n=5,  fast=3, slow=20)
        kama_slow = calc_kama(close, n=20, fast=2, slow=40)
        ao_arr    = calc_ao_fast_arr(high, low)
        rsi_arr   = calc_rsi_arr(close, 14)
        rsi5_arr  = calc_rsi_arr(close, 5)
        baff_arr  = calc_baff_arr(high, low)
        er_arr    = calc_er_arr(close)
        sar_arr, sar_bull_arr = calc_sar_arr(high, low)
        vol_r_arr = calc_vol_ratio_arr(volume)

        zona_arr = [get_zona(close[i], kama_fast[i], kama_slow[i]) for i in range(len(close))]
        segnale_arr = []
        for i in range(len(close)):
            s = get_segnale(zona_arr[i], ao_arr[i] if i<len(ao_arr) else 0,
                             vol_r_arr[i], er_arr[i], baff_arr[i],
                             kama_fast[i], kama_slow[i], regime_name, sar_bull_arr[i])
            segnale_arr.append(s)

        # ── stato live (ultima barra) ──
        kf, ks, lc = kama_fast[-1], kama_slow[-1], close[-1]
        zona = zona_arr[-1]
        score = calc_score(zona, ao_arr[-1], vol_r_arr[-1], er_arr[-1], baff_arr[-1], regime_mult)
        entry_date = '—'
        cur_z = zona_arr[-1]
        for idx in range(len(zona_arr)-2, max(0,len(zona_arr)-60), -1):
            if zona_arr[idx] != cur_z:
                entry_date = datetime.datetime.fromtimestamp(ts[idx+1]).strftime('%d/%m %H:%M')
                break

        live = {
            'ticker': info['t'], 'yahoo': symbol, 'nome': info.get('n',''),
            'segnale': segnale_arr[-1], 'zona': zona, 'score': sf(score),
            'prezzo': sf(round(lc,4)) if lc is not None else None,
            'kama_fast': sf(round(kf,4)) if kf else None,
            'kama_slow': sf(round(ks,4)) if ks else None,
            'er': sf(er_arr[-1]), 'baff': sf(baff_arr[-1]), 'ao': sf(ao_arr[-1]),
            'rsi': sf(rsi_arr[-1]), 'rsi5': sf(rsi5_arr[-1]),
            'volRatio': sf(vol_r_arr[-1]),
            'sar': sf(round(sar_arr[-1],4)) if sar_arr[-1] else None,
            'sarBull': sar_bull_arr[-1],
            'entryDate': entry_date,
            'perfOggi':  sf(round((lc/close[-2]-1)*100,2))  if len(close)>2  else 0,
            'perfSett':  sf(round((lc/close[-6]-1)*100,2))  if len(close)>6  else 0,
            'perfMese':  sf(round((lc/close[-21]-1)*100,2)) if len(close)>21 else 0,
        }

        # ── file chart per il widget scannerv3 ──
        bars = [[ts[i], sf(round(openp[i],4)), sf(round(high[i],4)), sf(round(low[i],4)),
                 sf(round(close[i],4)), int(volume[i]) if volume[i] is not None and not math.isnan(volume[i]) else 0]
                for i in range(len(close))]
        chart = {
            'sym': symbol, 'ticker': info['t'], 'nome': info.get('n',''),
            'd': bars,
            'kama_d': [sf(round(v,4)) if v is not None else None for v in kama_fast],
            'kamaSlow_d': [sf(round(v,4)) if v is not None else None for v in kama_slow],
            'sar_d': [sf(round(v,4)) if v is not None else None for v in sar_arr],
            'sarBull_d': sar_bull_arr,
            'ao_d': [sf(round(v,4)) for v in ao_arr],
            'rsi_d': [sf(v) for v in rsi_arr], 'rsi5_d': [sf(v) for v in rsi5_arr],
            'baff_d': baff_arr, 'er_d': [sf(v) for v in er_arr],
            'segnale_d': segnale_arr, 'zona_d': zona_arr,
        }
        return live, chart
    except Exception as e:
        print(f"  {info['t']}: errore {e}")
        return None, None

def main():
    import os
    now = datetime.datetime.now()
    print(f"RAPTOR Portafoglio Fetch — {now.strftime('%Y-%m-%d %H:%M')}")
    os.makedirs(CHARTS_DIR, exist_ok=True)

    vix, vstoxx = fetch_vix()
    regime = get_regime_vix(vix, vstoxx)
    print(f"VIX={vix} VSTOXX={vstoxx} Regime={regime['regime']}")

    live_results = []
    chart_index = []
    errors = 0
    for i, info in enumerate(TICKERS):
        live, chart = process_ticker(info, regime['mult'], regime['regime'])
        if live:
            live_results.append(live)
            fname = info['y'].replace('.', '_') + '.json'
            try:
                with open(f"{CHARTS_DIR}/{fname}", 'w', encoding='utf-8') as f:
                    json.dump(chart, f, ensure_ascii=False, separators=(',',':'), allow_nan=False)
                chart_index.append({'t': info['t'], 'y': info['y'], 'f': fname})
            except ValueError as e:
                print(f"  {info['t']}: NaN/Infinity residuo nel chart JSON, scarto ({e})")
                live_results.pop()  # niente prezzo live senza grafico coerente
                errors += 1
        else:
            errors += 1
        if (i+1) % 10 == 0:
            print(f"  {i+1}/{len(TICKERS)} — ok:{len(live_results)} err:{errors}")
        time.sleep(0.3)

    with open(f"{CHARTS_DIR}/index.json", 'w', encoding='utf-8') as f:
        json.dump({'index': chart_index}, f, ensure_ascii=False)

    output = {
        'timestamp': now.isoformat(),
        'timestamp_it': now.strftime('%d/%m/%Y %H:%M'),
        'total': len(TICKERS), 'ok': len(live_results), 'errors': errors,
        'vix': sf(vix), 'vstoxx': sf(vstoxx),
        'regime': regime['regime'], 'regime_mult': regime['mult'],
        'data': live_results,
    }
    with open('raptor_portafoglio_live.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, separators=(',',':'), allow_nan=False)

    print(f"\nSalvato raptor_portafoglio_live.json — {len(live_results)} OK, {errors} errori")

if __name__ == '__main__':
    main()
