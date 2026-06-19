from flask import Flask, jsonify, render_template_string
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from enum import Enum
import os
import sys
import logging
import time

logger = logging.getLogger(__name__)

app = Flask(__name__)
_start_time = __import__('time').time()

# Add project to path for brain imports
sys.path.insert(0, os.path.dirname(__file__))
from brain_v1 import Brain
from brain_v2 import BrainV2
from brain_v3 import BrainV3
from brain_v4 import BrainV4
from brain_v5 import BrainV5
from brain_v6 import BrainV6
from brain_v7 import BrainV7
from brain_v8 import BrainV8
from brain_v9 import BrainV9
from brain_v10 import BrainV10
from brain_v11 import BrainV11

# ==========================================
# CONFIG
# ==========================================
from config import (
    MAGIC_NUMBER, SCAN_SYMBOLS,
    is_system_magic, get_magic_info,
)

# Initialize full brain chain once — fallback if main app hasn't registered yet
try:
    import shared_state
    _brain = shared_state.get_brain_chain()
except Exception:
    _brain = None

if _brain is None:
    logger.warning("Dashboard: No brain chain from shared_state — will use zero data until main app registers")
# ==========================================

HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Autonomous Forex AutoTrader — Live Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:#0a0e17;color:#e0e0e0;line-height:1.4}
.header{background:linear-gradient(135deg,#0d1b2a 0%,#1b2838 50%,#0d1b2a 100%);padding:10px 20px;display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #00d4ff;position:sticky;top:0;z-index:100}
.header h1{font-size:16px;color:#00d4ff;letter-spacing:2px;font-weight:800}
.header .status{display:flex;align-items:center;gap:8px;font-size:11px;color:#9ca3af}
.dot{width:8px;height:8px;border-radius:50%;animation:pulse 2s infinite;display:inline-block}
.dot.green{background:#00ff88;box-shadow:0 0 6px #00ff88}
.dot.red{background:#ff4444;box-shadow:0 0 6px #ff4444}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.main{padding:6px 12px;display:flex;flex-direction:column;gap:6px}
.section{border-radius:8px;overflow:hidden;margin-bottom:6px}
.section-head{padding:8px 14px;display:flex;align-items:center;gap:8px;font-size:13px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;border-left:4px solid}
.section-head.blue{background:linear-gradient(90deg,rgba(0,123,255,.15),rgba(0,123,255,.05));border-left-color:#007bff;color:#007bff}
.section-head.green{background:linear-gradient(90deg,rgba(0,255,136,.12),rgba(0,255,136,.04));border-left-color:#00ff88;color:#00ff88}
.section-head.cyan{background:linear-gradient(90deg,rgba(0,212,255,.12),rgba(0,212,255,.04));border-left-color:#00d4ff;color:#00d4ff}
.section-head.orange{background:linear-gradient(90deg,rgba(255,165,0,.12),rgba(255,165,0,.04));border-left-color:#ffa500;color:#ffa500}
.section-head.purple{background:linear-gradient(90deg,rgba(168,85,247,.12),rgba(168,85,247,.04));border-left-color:#a855f7;color:#a855f7}
.section-head.teal{background:linear-gradient(90deg,rgba(20,184,166,.12),rgba(20,184,166,.04));border-left-color:#14b8a6;color:#14b8a6}
.section-head.yellow{background:linear-gradient(90deg,rgba(251,191,36,.12),rgba(251,191,36,.04));border-left-color:#fbbf24;color:#fbbf24}
.section-head.pink{background:linear-gradient(90deg,rgba(236,72,153,.12),rgba(236,72,153,.04));border-left-color:#ec4899;color:#ec4899}
.section-head.lime{background:linear-gradient(90deg,rgba(132,204,22,.12),rgba(132,204,22,.04));border-left-color:#84cc16;color:#84cc16}
.section-body{background:#111827;padding:8px 12px;display:grid;gap:6px}
.grid-2{display:grid;grid-template-columns:repeat(2,1fr);gap:6px}
.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}
.grid-5{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}
.card{background:#0d1b2a;border:1px solid #1e3a5f;border-radius:6px;padding:8px 10px;position:relative;overflow:hidden}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px}
.card.blue::before{background:linear-gradient(90deg,#007bff,#0056b3)}
.card.green::before{background:linear-gradient(90deg,#00ff88,#00cc6a)}
.card.red::before{background:linear-gradient(90deg,#ff4444,#cc0000)}
.card.cyan::before{background:linear-gradient(90deg,#00d4ff,#0099cc)}
.card.orange::before{background:linear-gradient(90deg,#ffa500,#cc8400)}
.card.purple::before{background:linear-gradient(90deg,#a855f7,#7c3aed)}
.card.teal::before{background:linear-gradient(90deg,#14b8a6,#0d9488)}
.card.yellow::before{background:linear-gradient(90deg,#fbbf24,#d97706)}
.card.pink::before{background:linear-gradient(90deg,#ec4899,#db2777)}
.card.lime::before{background:linear-gradient(90deg,#84cc16,#65a30d)}
.card-label{font-size:9px;color:#6b7280;text-transform:uppercase;letter-spacing:1px;margin-bottom:2px}
.card-value{font-size:18px;font-weight:800;line-height:1.2;transition:color .3s}
.card-sub{font-size:10px;color:#9ca3af;margin-top:2px}
.c-green{color:#00ff88}.c-red{color:#ff4444}.c-blue{color:#007bff}.c-cyan{color:#00d4ff}
.c-orange{color:#ffa500}.c-purple{color:#a855f7}.c-teal{color:#14b8a6}.c-yellow{color:#fbbf24}.c-pink{color:#ec4899}
table{width:100%;border-collapse:collapse;font-size:11px}
th{background:#0d1b2a;padding:6px 8px;text-align:left;font-size:9px;color:#6b7280;text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid #1e3a5f}
td{padding:5px 8px;border-bottom:1px solid #1a2332;font-size:11px;transition:background .2s}
tr:hover{background:rgba(30,58,95,.3)}
.pnl-pos{color:#00ff88;font-weight:700}.pnl-neg{color:#ff4444;font-weight:700}
.signal{display:inline-block;padding:2px 8px;border-radius:10px;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;transition:all .3s}
.signal.buy{background:rgba(0,255,136,.15);color:#00ff88;border:1px solid rgba(0,255,136,.3)}
.signal.sell{background:rgba(255,68,68,.15);color:#ff4444;border:1px solid rgba(255,68,68,.3)}
.signal.neutral{background:rgba(107,114,128,.1);color:#6b7280;border:1px solid rgba(107,114,128,.2)}
.signal.active{background:rgba(0,212,255,.15);color:#00d4ff;border:1px solid rgba(0,212,255,.3)}
.bar-bg{background:#1e3a5f;border-radius:3px;height:6px;overflow:hidden}
.bar-fill{height:6px;border-radius:3px;transition:width .5s ease,background .3s}
.bar-fill.green{background:linear-gradient(90deg,#00ff88,#00d4ff)}
.bar-fill.red{background:linear-gradient(90deg,#ff4444,#fbbf24)}
.bar-fill.orange{background:linear-gradient(90deg,#ffa500,#ff6600)}
.mr{display:flex;justify-content:space-between;align-items:center;padding:3px 0;font-size:11px}
.mr .k{color:#9ca3af;font-size:10px}
.mr .v{font-weight:600;font-size:12px;transition:color .3s}
.live-dot{width:6px;height:6px;border-radius:50%;display:inline-block;margin-right:4px;animation:pulse 1s infinite}
.live-dot.on{background:#00ff88;box-shadow:0 0 4px #00ff88}
.live-dot.off{background:#ff4444;box-shadow:0 0 4px #ff4444}
.live-dot.idle{background:#ffa500;box-shadow:0 0 4px #ffa500}
.process-row{display:flex;align-items:center;gap:6px;padding:4px 8px;background:#0d1b2a;border-radius:4px;font-size:10px;border:1px solid #1e3a5f}
.process-row .name{width:120px;font-weight:700;color:#00d4ff}
.process-row .status{flex:1}
.process-row .metric{width:80px;text-align:right;color:#9ca3af}
footer{text-align:center;padding:8px;color:#374151;font-size:9px;border-top:1px solid #1e3a5f}
@media(max-width:768px){.grid-3,.grid-4,.grid-5{grid-template-columns:repeat(2,1fr)}}
@media(max-width:480px){.grid-2,.grid-3,.grid-4,.grid-5{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="header">
  <h1>&#9670; AUTONOMOUS FOREX AUTOTRADER</h1>
  <div class="status">
    <div class="dot" id="hdr-dot"></div>
    <span id="hdr-status">Connecting...</span>
    <span style="color:#374151">|</span>
    <span id="hdr-clock">--:--:--</span>
    <span style="color:#374151">|</span>
    <span id="hdr-ticks" style="color:#00d4ff">0 ticks/s</span>
  </div>
</div>

<div class="main">

<!-- ACCOUNT -->
<div class="section"><div class="section-head blue">&#9670; ACCOUNT</div><div class="section-body">
  <div class="grid-5">
    <div class="card blue"><div class="card-label">Balance</div><div class="card-value c-blue" id="v-bal">$0.00</div></div>
    <div class="card green"><div class="card-label">Equity</div><div class="card-value c-green" id="v-eq">$0.00</div></div>
    <div class="card blue"><div class="card-label">Free Margin</div><div class="card-value c-blue" id="v-free">$0.00</div></div>
    <div class="card green"><div class="card-label">Floating P&L</div><div class="card-value c-green" id="v-pnl">$0.00</div></div>
    <div class="card green"><div class="card-label">Daily P&L</div><div class="card-value c-green" id="v-dpnl">$0.00</div></div>
  </div>
</div></div>

<!-- PERFORMANCE -->
<div class="section"><div class="section-head green">&#9670; PERFORMANCE</div><div class="section-body">
  <div class="grid-5">
    <div class="card green"><div class="card-label">Win Rate</div><div class="card-value c-green" id="v-wr">0%</div></div>
    <div class="card orange"><div class="card-label">Profit Factor</div><div class="card-value c-orange" id="v-pf">0.00</div></div>
    <div class="card green"><div class="card-label">Drawdown</div><div class="card-value c-green" id="v-dd">0%</div></div>
    <div class="card yellow"><div class="card-label">Daily Trades</div><div class="card-value c-yellow" id="v-dt">0/20</div></div>
    <div class="card cyan"><div class="card-label">Open / Max</div><div class="card-value c-cyan" id="v-oc">0/3</div></div>
  </div>
</div></div>

<!-- PROCESSES -->
<div class="section"><div class="section-head pink">&#9670; RUNNING PROCESSES</div><div class="section-body" id="v-processes" style="display:flex;flex-direction:column;gap:4px">
  <div class="process-row"><span class="name"><span class="live-dot off"></span>SymbolAnalyzer</span><span class="status" id="p-analyzer">Waiting...</span><span class="metric" id="p-ana-ct">0 analyzed</span></div>
  <div class="process-row"><span class="name"><span class="live-dot off"></span>TradeExecutor</span><span class="status" id="p-executor">Idle</span><span class="metric" id="p-exec-ct">0 executed</span></div>
  <div class="process-row"><span class="name"><span class="live-dot off"></span>PositionManager</span><span class="status" id="p-posmgr">Monitoring</span><span class="metric" id="p-pos-ct">0 managed</span></div>
  <div class="process-row"><span class="name"><span class="live-dot off"></span>ParallelScanner</span><span class="status" id="p-scanner">Idle</span><span class="metric" id="p-scan-ct">0 scanned</span></div>
  <div class="process-row"><span class="name"><span class="live-dot off"></span>SystemMonitor</span><span class="status" id="p-sysmon">OK</span><span class="metric" id="p-health">100/100</span></div>
  <div class="process-row"><span class="name"><span class="live-dot off"></span>BrainChain V11</span><span class="status" id="p-brain">Ready</span><span class="metric" id="p-brain-ct">0 decisions</span></div>
</div></div>

<!-- V11 TRADING METHOD -->
<div class="section"><div class="section-head purple">&#9670; V11 — TRADING METHOD</div><div class="section-body">
  <div class="grid-3">
    <div class="card purple">
      <div class="card-label">Active Method</div>
      <div class="mr"><span class="k">Method</span><span class="signal active" id="v11-method">TECHNICAL</span></div>
      <div class="mr"><span class="k">Secondary</span><span class="v" id="v11-sec">N/A</span></div>
      <div class="mr"><span class="k">SL/TP</span><span class="v" id="v11-sltp">1.5x / 2.5x</span></div>
      <div class="mr"><span class="k">Risk</span><span class="v" id="v11-risk">1.0%</span></div>
    </div>
    <div class="card purple">
      <div class="card-label">Method Scores</div>
      <div id="v11-scores"></div>
    </div>
    <div class="card purple">
      <div class="card-label">Method Performance</div>
      <div id="v11-perf"></div>
    </div>
  </div>
</div></div>

<!-- V1 STRATEGY SIGNALS -->
<div class="section"><div class="section-head cyan">&#9670; V1 — STRATEGY SIGNALS</div><div class="section-body">
  <div class="grid-3">
    <div class="card cyan">
      <div class="card-label">Active Signals</div>
      <div id="v1-signals"></div>
      <div style="margin-top:4px;padding-top:4px;border-top:1px solid #1e3a5f">
        <div class="mr"><span class="k" style="font-weight:700">Consensus</span><span class="signal neutral" id="v1-cons">NEUTRAL</span></div>
        <div class="mr"><span class="k">Confidence</span><span class="v" id="v1-conf">0.000</span></div>
      </div>
    </div>
    <div class="card cyan"><div class="card-label">Strategy Weights</div><div id="v1-weights"></div></div>
    <div class="card cyan"><div class="card-label">Bayesian</div><div id="v1-bayes"></div></div>
  </div>
</div></div>

<!-- V2 MARKET CONTEXT -->
<div class="section"><div class="section-head orange">&#9670; V2 — MARKET CONTEXT</div><div class="section-body">
  <div class="grid-3">
    <div class="card orange">
      <div class="card-label">Regime</div>
      <div class="mr"><span class="k">Current</span><span class="signal neutral" id="v2-regime">unknown</span></div>
      <div class="mr"><span class="k">ADX</span><span class="v" id="v2-adx">0</span></div>
      <div class="mr"><span class="k">Squeeze</span><span class="signal neutral" id="v2-sq">NO</span></div>
    </div>
    <div class="card orange">
      <div class="card-label">Session</div>
      <div class="mr"><span class="k">Current</span><span class="signal neutral" id="v2-sess">unknown</span></div>
      <div class="mr"><span class="k">Kill Zone</span><span class="signal neutral" id="v2-kz">NO</span></div>
      <div class="mr"><span class="k">Session WR</span><span class="v" id="v2-swr">50%</span></div>
    </div>
    <div class="card orange">
      <div class="card-label">Patterns</div>
      <div id="v2-patterns"><span class="k">None detected</span></div>
      <div class="mr"><span class="k">Fractal</span><span class="v" id="v2-fractal">neutral</span></div>
      <div class="mr"><span class="k">Z-Score</span><span class="v" id="v2-zscore">0</span></div>
    </div>
  </div>
</div></div>

<!-- V3 EFFICIENCY -->
<div class="section"><div class="section-head teal">&#9670; V3 — EFFICIENCY</div><div class="section-body">
  <div class="grid-3">
    <div class="card teal">
      <div class="card-label">Circuit Breaker</div>
      <div class="mr"><span class="k">Status</span><span class="signal neutral" id="v3-circuit">CLOSED</span></div>
      <div class="mr"><span class="k">Consec Losses</span><span class="v" id="v3-consec">0</span></div>
    </div>
    <div class="card teal">
      <div class="card-label">Execution</div>
      <div class="mr"><span class="k">Avg Spread</span><span class="v" id="v3-spread">0pts</span></div>
      <div class="mr"><span class="k">Avg Time</span><span class="v" id="v3-time">0ms</span></div>
    </div>
    <div class="card teal">
      <div class="card-label">Analysis</div>
      <div class="mr"><span class="k">Total</span><span class="v" id="v3-total">0</span></div>
      <div class="mr"><span class="k">Skip Rate</span><span class="v" id="v3-skip">0%</span></div>
    </div>
  </div>
</div></div>

<!-- V9 SYSTEM -->
<div class="section"><div class="section-head pink">&#9670; V9 — SYSTEM</div><div class="section-body">
  <div class="grid-4">
    <div class="card pink"><div class="card-label">Health</div><div class="card-value c-green" id="v9-health">100/100</div><div class="bar-bg" style="margin-top:4px"><div class="bar-fill green" id="v9-hbar" style="width:100%"></div></div></div>
    <div class="card pink"><div class="card-label">CPU</div><div class="card-value c-green" id="v9-cpu">0%</div><div class="bar-bg" style="margin-top:4px"><div class="bar-fill green" id="v9-cpubar" style="width:0%"></div></div></div>
    <div class="card pink"><div class="card-label">Memory</div><div class="card-value c-green" id="v9-mem">0%</div><div class="bar-bg" style="margin-top:4px"><div class="bar-fill green" id="v9-membar" style="width:0%"></div></div></div>
    <div class="card pink"><div class="card-label">Processes</div><div class="mr"><span class="k">MT5</span><span class="signal neutral" id="v9-mt5">STOP</span></div><div class="mr"><span class="k">Python</span><span class="signal neutral" id="v9-py">STOP</span></div></div>
  </div>
</div></div>

<!-- OPEN POSITIONS -->
<div class="section"><div class="section-head yellow" id="v-pos-head">&#9670; OPEN POSITIONS (0)</div><div class="section-body" style="overflow-x:auto">
  <table><tr><th>Ticket</th><th>Symbol</th><th>Type</th><th>Vol</th><th>Open</th><th>Current</th><th>SL</th><th>TP</th><th>P&L</th><th>Duration</th></tr>
  <tbody id="v-positions"><tr><td colspan="10" style="text-align:center;color:#374151;padding:16px">No open positions</td></tr></tbody></table>
</div></div>

<!-- LIVE ANALYSIS -->
<div class="section"><div class="section-head cyan">&#9670; LIVE ANALYSIS — TICK-DRIVEN</div><div class="section-body" style="overflow-x:auto">
  <table><tr><th>Symbol</th><th>Status</th><th>Tick</th><th>Age</th><th>Bid</th><th>Ask</th><th>Spread</th><th>Action</th><th>Direction</th><th>Confidence</th><th>Method</th><th>Regime</th><th>Session</th><th>MS</th><th>Updated</th></tr>
  <tbody id="v-analysis"><tr><td colspan="15" style="text-align:center;color:#374151;padding:16px">Waiting for ticks...</td></tr></tbody></table>
  <div style="margin-top:6px;padding:6px 10px;background:#0d1b2a;border-radius:4px;display:flex;gap:16px;font-size:10px;color:#9ca3af" id="v-ana-sum">
    <span>Total: <b class="c-cyan">0</b></span><span>Active: <b class="c-green">0</b></span><span>Closed: <b class="c-red">0</b></span><span>Signals: <b class="c-yellow">0</b></span><span>Avg: <b class="c-cyan">0ms</b></span>
  </div>
</div></div>

<!-- WATCHLIST -->
<div class="section"><div class="section-head yellow">&#9670; WATCHLIST</div><div class="section-body" style="overflow-x:auto">
  <table><tr><th>Symbol</th><th>Bid</th><th>Ask</th><th>Spread</th><th>ATR</th><th>Vol</th><th>Trend</th></tr>
  <tbody id="v-watchlist"></tbody></table>
</div></div>

<!-- HISTORY -->
<div class="section"><div class="section-head blue">&#9670; RECENT TRADES</div><div class="section-body" style="overflow-x:auto">
  <table><tr><th>Time</th><th>Symbol</th><th>Type</th><th>Vol</th><th>Price</th><th>Profit</th><th>Comment</th></tr>
  <tbody id="v-history"><tr><td colspan="7" style="text-align:center;color:#374151;padding:16px">No recent trades</td></tr></tbody></table>
</div></div>

</div>
<footer>Autonomous Forex AutoTrader — Live Dashboard — Real-Time AJAX Updates @ 500ms</footer>
<script>
const $=s=>document.getElementById(s);
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function pnlC(v){return v>=0?'pnl-pos':'pnl-neg'}
function pnlS(v){return v>=0?'+':''}
function sig(t,t2){return'<span class="signal '+t+'">'+esc(t2)+'</span>'}

async function poll(){
  try{
    const r=await fetch('/api/data');
    const d=await r.json();

    // Header
    const dot=$('hdr-dot');if(dot)dot.className='dot '+(d.mt5_connected?'green':'red');
    const st=$('hdr-status');if(st)st.textContent=d.mt5_connected?'MT5 Connected':'Disconnected';
    const ck=$('hdr-clock');if(ck)ck.textContent=d.clock||'--:--:--';

    // Tick counter
    _tickCount++;
    const now=Date.now();
    if(now-_lastTick>=1000){
      const tk=$('hdr-ticks');if(tk)tk.textContent=_tickCount+' updates/s';
      _tickCount=0;_lastTick=now;
    }

    // Account
    let e;
    if(e=$('v-bal'))e.textContent='$'+(d.balance||0).toLocaleString(undefined,{minimumFractionDigits:2});
    if(e=$('v-eq')){e.textContent='$'+(d.equity||0).toLocaleString(undefined,{minimumFractionDigits:2});e.parentElement.className='card '+(d.equity>=d.balance?'green':'red')}
    if(e=$('v-free'))e.textContent='$'+(d.free_margin||0).toLocaleString(undefined,{minimumFractionDigits:2});
    if(e=$('v-pnl')){const v=d.floating_pnl||0;e.textContent=pnlS(v)+'$'+Math.abs(v).toLocaleString(undefined,{minimumFractionDigits:2});e.className='card-value '+pnlC(v);e.parentElement.className='card '+(v>=0?'green':'red')}
    if(e=$('v-dpnl')){const v=d.daily_pnl||0;e.textContent=pnlS(v)+'$'+Math.abs(v).toLocaleString(undefined,{minimumFractionDigits:2});e.className='card-value '+pnlC(v);e.parentElement.className='card '+(v>=0?'green':'red')}

    // Performance
    if(e=$('v-wr')){e.textContent=(d.win_rate||0).toFixed(1)+'%';e.className='card-value '+((d.win_rate||0)>=50?'c-green':'c-red');e.parentElement.className='card '+((d.win_rate||0)>=50?'green':'red')}
    if(e=$('v-pf'))e.textContent=(d.profit_factor||0).toFixed(2);
    if(e=$('v-dd')){e.textContent=(d.drawdown||0).toFixed(1)+'%';e.className='card-value '+((d.drawdown||0)<3?'c-green':'c-red')}
    if(e=$('v-dt'))e.textContent=(d.daily_trades||0)+'/20';
    if(e=$('v-oc'))e.textContent=(d.open_count||0)+'/3';

    // Processes — live status dots
    const analyzerActive=d.analysis_active_count>0;
    setProc('p-analyzer',analyzerActive?'Analyzing '+d.analysis_active_count+' symbols':'Waiting',analyzerActive);
    setProc('p-executor','Idle',false);
    setProc('p-posmgr','Monitoring '+(d.open_count||0)+' positions',d.open_count>0);
    setProc('p-scanner','Scanning',true);
    setProc('p-sysmon',(d.health_score||0)>70?'OK':'WARNING',(d.health_score||0)>70);
    setProc('p-brain','Active — '+(d.v11?d.v11.method:'N/A'),true);
    if(e=$('p-ana-ct'))e.textContent=(d.analysis_count||0)+' analyzed';
    if(e=$('p-exec-ct'))e.textContent=(d.daily_trades||0)+' executed';
    if(e=$('p-pos-ct'))e.textContent=(d.open_count||0)+' managed';
    if(e=$('p-health'))e.textContent=(d.health_score||0).toFixed(0)+'/100';

    // V11
    if(d.v11){
      if(e=$('v11-method'))e.textContent=d.v11.method||'TECHNICAL';
      if(e=$('v11-sec'))e.textContent=d.v11.secondary_method||'N/A';
      if(e=$('v11-sltp'))e.textContent=(d.v11.config.sl_atr_mult||1.5)+'x / '+(d.v11.config.tp_atr_mult||2.5)+'x';
      if(e=$('v11-risk'))e.textContent=(d.v11.config.risk_per_trade||1)+'%';
      let sc='';if(d.v11.method_scores)for(const[k,v]of Object.entries(d.v11.method_scores))sc+='<div class="mr"><span class="k">'+k+'</span><span class="v">'+v.toFixed(3)+'</span></div>';
      if(e=$('v11-scores'))e.innerHTML=sc||'<span class="k">No data</span>';
      let pf='';if(d.v11.method_performance)for(const[k,v]of Object.entries(d.v11.method_performance)){if(v.wins+v.losses>0)pf+='<div class="mr"><span class="k">'+k+'</span><span class="v">'+(v.wins/(v.wins+v.losses)*100).toFixed(0)+'% ('+v.wins+'W/'+v.losses+'L)</span></div>';}
      if(e=$('v11-perf'))e.innerHTML=pf||'<span class="k">No data</span>';
    }

    // V1 Signals
    if(d.signals){
      let h='';for(const[n,s]of Object.entries(d.signals)){const c=s.direction_str==='BUY'?'buy':s.direction_str==='SELL'?'sell':'neutral';h+='<div class="mr"><span class="k">'+n+'</span>'+sig(c,s.direction_str+' '+s.confidence.toFixed(2))+'</div>';}
      if(e=$('v1-signals'))e.innerHTML=h;
      if(e=$('v1-cons')){e.textContent=d.consensus;e.className='signal '+d.consensus.toLowerCase()}
      if(e=$('v1-conf'))e.textContent=(d.confidence||0).toFixed(3);
    }
    if(d.strategy_weights){let h='';for(const[k,v]of Object.entries(d.strategy_weights))h+='<div class="mr"><span class="k">'+k+'</span><span class="v">'+v.toFixed(3)+'</span></div>';if(e=$('v1-weights'))e.innerHTML=h;}
    if(d.bayesian_probs){let h='';for(const[k,v]of Object.entries(d.bayesian_probs))h+='<div class="mr"><span class="k">'+k+'</span><span class="v '+(v>0.55?'c-green':'c-red')+'">'+(v*100).toFixed(1)+'%</span></div>';if(e=$('v1-bayes'))e.innerHTML=h;}

    // V2
    if(e=$('v2-regime')){e.textContent=d.regime||'unknown';e.className='signal '+'trend' in (d.regime||'')?'active':'neutral'}
    if(e=$('v2-adx'))e.textContent=(d.adx||0).toFixed(1);
    if(e=$('v2-sq')){e.textContent=d.squeeze?'YES':'NO';e.className='signal '+(d.squeeze?'active':'neutral')}
    if(e=$('v2-sess')){e.textContent=d.session||'unknown';e.className='signal '+d.is_kill_zone?'active':'neutral'}
    if(e=$('v2-kz')){e.textContent=d.is_kill_zone?'YES':'NO';e.className='signal '+(d.is_kill_zone?'active':'neutral')}
    if(e=$('v2-swr'))e.textContent=(d.session_wr||50).toFixed(0)+'%';
    if(d.candle_patterns&&d.candle_patterns.length){let h='';d.candle_patterns.forEach(p=>{h+=sig('active',p)+' '});if(e=$('v2-patterns'))e.innerHTML=h;}
    if(e=$('v2-fractal'))e.textContent=d.fractal_trend||'neutral';
    if(e=$('v2-zscore'))e.textContent=(d.z_score||0).toFixed(2);

    // V3
    if(e=$('v3-circuit')){e.textContent=d.circuit_open?'OPEN':'CLOSED';e.className='signal '+(d.circuit_open?'active':'neutral')}
    if(e=$('v3-consec'))e.textContent=d.consec_losses||0;
    if(e=$('v3-spread'))e.textContent=(d.avg_spread||0).toFixed(0)+'pts';
    if(e=$('v3-time'))e.textContent=(d.avg_analyze_ms||0).toFixed(1)+'ms';
    if(e=$('v3-total'))e.textContent=d.analysis_count||0;
    if(e=$('v3-skip'))e.textContent=(d.skip_rate||0).toFixed(0)+'%';

    // V9
    if(e=$('v9-health')){e.textContent=(d.health_score||0).toFixed(0)+'/100';e.className='card-value c-'+((d.health_score||0)>70?'green':(d.health_score||0)>40?'yellow':'red')}
    if(e=$('v9-hbar')){e.style.width=(d.health_score||0)+'%';e.className='bar-fill '+((d.health_score||0)>70?'green':(d.health_score||0)>40?'orange':'red')}
    if(e=$('v9-cpu')){e.textContent=(d.cpu_overall||0).toFixed(1)+'%';e.className='card-value '+((d.cpu_overall||0)<70?'c-green':'c-red')}
    if(e=$('v9-cpubar')){e.style.width=(d.cpu_overall||0)+'%';e.className='bar-fill '+((d.cpu_overall||0)<70?'green':'red')}
    if(e=$('v9-mem')){e.textContent=(d.mem_percent||0).toFixed(1)+'%';e.className='card-value '+((d.mem_percent||0)<70?'c-green':'c-red')}
    if(e=$('v9-membar')){e.style.width=(d.mem_percent||0)+'%';e.className='bar-fill '+((d.mem_percent||0)<70?'green':'red')}
    if(e=$('v9-mt5')){e.textContent=d.mt5_running?'RUN':'STOP';e.className='signal '+(d.mt5_running?'active':'neutral')}
    if(e=$('v9-py')){e.textContent=d.python_running?'RUN':'STOP';e.className='signal '+(d.python_running?'active':'neutral')}

    // Positions
    if(e=$('v-pos-head'))e.innerHTML='&#9670; OPEN POSITIONS ('+(d.open_count||0)+')';
    if(d.positions&&d.positions.length){let h='';d.positions.forEach(p=>{h+='<tr><td>'+p.ticket+'</td><td style="font-weight:700">'+p.symbol+'</td><td>'+sig(p.type==0?'buy':'sell',p.type==0?'BUY':'SELL')+'</td><td>'+p.volume+'</td><td>'+p.price_open.toFixed(5)+'</td><td>'+p.price_current.toFixed(5)+'</td><td>'+p.sl.toFixed(5)+'</td><td>'+p.tp.toFixed(5)+'</td><td class="'+pnlC(p.profit)+'">'+pnlS(p.profit)+'$'+Math.abs(p.profit).toFixed(2)+'</td><td>'+p.duration+'</td></tr>'});if(e=$('v-positions'))e.innerHTML=h;}
    else if(e=$('v-positions'))e.innerHTML='<tr><td colspan="10" style="text-align:center;color:#374151;padding:16px">No open positions</td></tr>';

    // Analysis
    if(d.analysis_status&&d.analysis_status.length){let h='';d.analysis_status.forEach(a=>{
      const mc=a.market_closed,sc=mc?'sell':a.action==='trade'?'buy':'neutral',st=mc?'CLOSED':a.action==='trade'?'SIGNAL':'IDLE';
      const ac=a.tick_age_ms<500?'c-green':a.tick_age_ms<2000?'c-yellow':'c-red';
      const rc=a.action==='trade'?'buy':a.action==='hold'?'neutral':'sell';
      const dc=a.direction==='BUY'?'buy':a.direction==='SELL'?'sell':'neutral';
      const cc=a.confidence>0.7?'c-green':a.confidence>0.5?'c-yellow':'';
      h+='<tr><td style="font-weight:700">'+a.symbol+'</td><td>'+sig(sc,st)+'</td><td>'+a.tick_time+'</td><td class="'+ac+'">'+a.tick_age_ms+'ms</td>';
      h+='<td>'+(a.bid?a.bid.toFixed(5):'---')+'</td><td>'+(a.ask?a.ask.toFixed(5):'---')+'</td><td>'+a.spread+'pts</td>';
      h+='<td>'+sig(rc,a.action.toUpperCase())+'</td><td>'+sig(dc,a.direction)+'</td>';
      h+='<td class="'+cc+'" style="font-weight:700">'+a.confidence.toFixed(3)+'</td>';
      h+='<td>'+sig('active',a.method)+'</td><td>'+sig('trend' in a.regime?'active':'neutral',a.regime)+'</td>';
      h+='<td>'+sig(a.session in['london','overlap','new_york']?'active':'neutral',a.session)+'</td>';
      h+='<td>'+a.analysis_ms+'ms</td><td>'+a.time+'</td></tr>';
    });if(e=$('v-analysis'))e.innerHTML=h;
    if(e=$('v-ana-sum'))e.innerHTML='<span>Total: <b class="c-cyan">'+d.analysis_status.length+'</b></span><span>Active: <b class="c-green">'+d.analysis_active_count+'</b></span><span>Closed: <b class="c-red">'+d.analysis_closed_count+'</b></span><span>Signals: <b class="c-yellow">'+d.analysis_signal_count+'</b></span><span>Avg: <b class="c-cyan">'+d.analysis_avg_ms+'ms</b></span>';
    }

    // Watchlist
    if(d.watchlist){let h='';d.watchlist.forEach(s=>{h+='<tr><td style="font-weight:700">'+esc(s.symbol)+'</td><td>'+s.bid.toFixed(5)+'</td><td>'+s.ask.toFixed(5)+'</td><td>'+s.spread+'</td><td>'+s.atr.toFixed(5)+'</td><td>'+sig(s.high_vol?'active':'neutral',s.high_vol?'HIGH':'LOW')+'</td><td>'+sig(s.trend.toLowerCase(),s.trend)+'</td></tr>'});if(e=$('v-watchlist'))e.innerHTML=h;}

    // History
    if(d.history){let h='';d.history.forEach(t=>{h+='<tr><td>'+esc(t.time)+'</td><td style="font-weight:700">'+esc(t.symbol)+'</td><td>'+sig(t.type==0?'buy':'sell',t.type==0?'BUY':'SELL')+'</td><td>'+t.volume+'</td><td>'+t.price.toFixed(5)+'</td><td class="'+pnlC(t.profit)+'">'+pnlS(t.profit)+'$'+Math.abs(t.profit).toFixed(2)+'</td><td>'+esc(t.comment)+'</td></tr>'});if(e=$('v-history'))e.innerHTML=h;}

  }catch(x){console.error('Poll error:',x)}
  setTimeout(poll,500);
}
poll();
</script>
</body>
</html>
"""


def get_dashboard_data():
    global _brain
    # Refresh brain reference from shared_state (main app may register after dashboard loads)
    try:
        import shared_state
        shared_brain = shared_state.get_brain_chain()
        if shared_brain is not None:
            _brain = shared_brain
    except Exception:
        pass

    data = {}
    try:
        connected = mt5.terminal_info() is not None
    except Exception as e:
        logger.warning("MT5 terminal check failed: %s", e)
        connected = False
    data['mt5_connected'] = connected
    if not connected:
        data['clock'] = datetime.now().strftime("%H:%M:%S")
        data['balance'] = 0
        data['equity'] = 0
        data['free_margin'] = 0
        data['floating_pnl'] = 0
        data['daily_pnl'] = 0
        data['daily_trades'] = 0
        data['win_rate'] = 0
        data['profit_factor'] = 0
        data['drawdown'] = 0
        data['open_count'] = 0
        data['positions'] = []
        data['signals'] = {}
        data['consensus'] = 'NEUTRAL'
        data['confidence'] = 0
        data['strategy_weights'] = {}
        data['bayesian_probs'] = {}
        data['regime'] = 'unknown'
        data['adx'] = 0
        data['squeeze'] = False
        data['range_pct'] = 0
        data['candle_patterns'] = []
        data['fractal_trend'] = 'neutral'
        data['z_score'] = 0
        data['session'] = 'unknown'
        data['is_kill_zone'] = False
        data['session_wr'] = 50
        data['circuit_open'] = False
        data['consec_losses'] = 0
        data['total_breaks'] = 0
        data['avg_spread'] = 0
        data['avg_slippage'] = 0
        data['decay_score'] = 1.0
        data['analysis_count'] = 0
        data['skip_count'] = 0
        data['skip_rate'] = 0
        data['avg_analyze_ms'] = 0
        data['edge_decaying'] = False
        data['edge_score'] = 0
        data['recent_wr'] = 0.5
        data['streak_str'] = 'N/A'
        data['auto_weights'] = {}
        data['disabled_strategies'] = []
        data['session_memory'] = {}
        data['health_score'] = 0
        data['cpu_overall'] = 0
        data['mem_percent'] = 0
        data['mt5_running'] = False
        data['python_running'] = False
        data['watchlist'] = []
        data['v11'] = {"method": "TECHNICAL", "secondary_method": None, "config": {}, "method_scores": {}, "method_performance": {}}
        data['history'] = []
        data['analysis_status'] = []
        data['analysis_active_count'] = 0
        data['analysis_closed_count'] = 0
        data['analysis_signal_count'] = 0
        data['analysis_avg_ms'] = 0
        return data

    data['clock'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        acct = mt5.account_info()
    except Exception as e:
        acct = None
    data['balance'] = acct.balance if acct else 0
    data['equity'] = acct.equity if acct else 0
    data['free_margin'] = acct.margin_free if acct else 0
    data['floating_pnl'] = acct.profit if acct else 0

    # V1 stats - read from shared_state (main app's brain)
    import shared_state
    engine_state = shared_state.get_engine_state()
    v1_report = {"win_rate": 0, "profit_factor": 0, "drawdown": 0}
    if engine_state:
        try:
            v1_report = engine_state.get_data("v1_report") or v1_report
        except Exception:
            pass
    # Fallback: compute from MT5 history
    if v1_report.get("win_rate", 0) == 0:
        try:
            all_deals = mt5.history_deals_get(datetime.now() - timedelta(days=30), datetime.now(), group="*")
            wins = sum(1 for d in (all_deals or []) if is_system_magic(d.magic) and d.entry == mt5.DEAL_ENTRY_OUT and d.profit > 0)
            losses = sum(1 for d in (all_deals or []) if is_system_magic(d.magic) and d.entry == mt5.DEAL_ENTRY_OUT and d.profit <= 0)
            total = wins + losses
            v1_report["win_rate"] = (wins / total * 100) if total > 0 else 0
        except Exception:
            pass
    data['win_rate'] = v1_report.get('win_rate', 0)
    data['profit_factor'] = v1_report.get('profit_factor', 0)
    data['drawdown'] = v1_report.get('drawdown', 0)

    now = datetime.now()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        deals = mt5.history_deals_get(start_of_day, now, group="*")
    except Exception as e:
        logger.debug("History deals fetch failed: %s", e)
        deals = None
    daily_pnl = 0
    daily_trades_count = 0
    for d in (deals or []):
        if is_system_magic(d.magic) and d.entry == mt5.DEAL_ENTRY_OUT:
            daily_pnl += d.profit
            daily_trades_count += 1
    data['daily_pnl'] = daily_pnl
    data['daily_trades'] = daily_trades_count

    # Open positions
    try:
        open_pos = mt5.positions_get()
    except Exception as e:
        logger.debug("Positions fetch failed: %s", e)
        open_pos = None
    my_pos = [p for p in (open_pos or []) if is_system_magic(p.magic)]
    data['open_count'] = len(my_pos)
    positions = []
    for p in my_pos:
        dur = (datetime.now() - datetime.fromtimestamp(p.time)).total_seconds()
        h, m = int(dur // 3600), int((dur % 3600) // 60)
        info = mt5.symbol_info(p.symbol)
        point = info.point if info else 0.0001
        if p.type == 0:
            pips = (p.price_current - p.price_open) / point
        else:
            pips = (p.price_open - p.price_current) / point
        positions.append({
            'ticket': p.ticket, 'symbol': p.symbol, 'type': p.type, 'volume': p.volume,
            'price_open': p.price_open, 'price_current': p.price_current,
            'sl': p.sl, 'tp': p.tp, 'profit': p.profit,
            'pips': round(pips, 1),
            'duration': f"{h}h {m}m" if h > 0 else f"{m}m"
        })
    data['positions'] = positions

    # V1 signals - read from shared_state first (last computed by SymbolAnalyzer)
    import shared_state
    all_analysis = shared_state.get_all_analysis()
    symbol = "EURUSD"
    
    # Try to get signals from the last analysis for the primary symbol
    signals_display = {}
    consensus = 'NEUTRAL'
    confidence = 0
    if all_analysis:
        # Use the first analyzed symbol's data
        for sym, analysis in all_analysis.items():
            if analysis.get('action') != 'hold' or analysis.get('confidence', 0) > 0:
                signals_display[sym] = {
                    'direction_str': analysis.get('direction', 'NEUTRAL'),
                    'confidence': analysis.get('confidence', 0),
                }
        if signals_display:
            buy_v = sum(1 for s in signals_display.values() if s['direction_str'] == 'BUY')
            sell_v = sum(1 for s in signals_display.values() if s['direction_str'] == 'SELL')
            consensus = 'BUY' if buy_v > sell_v else 'SELL' if sell_v > buy_v else 'NEUTRAL'
            confidence = max((s['confidence'] for s in signals_display.values()), default=0)
    
    # Fallback: try to compute from brain chain
    if not signals_display:
        try:
            v1_signals = _brain.v10.v9.v8.v7.v6.v5.v4.v3.v2.v1.analyzer.calculate_all_signals(symbol, mt5.TIMEFRAME_M1)
            for name, sig in v1_signals.items():
                d = sig.get('direction', 0)
                signals_display[name] = {
                    'direction_str': 'BUY' if d == 1 else 'SELL' if d == -1 else 'NEUTRAL',
                    'confidence': sig.get('confidence', 0),
                }
            if signals_display:
                buy_v = sum(1 for s in signals_display.values() if s['direction_str'] == 'BUY')
                sell_v = sum(1 for s in signals_display.values() if s['direction_str'] == 'SELL')
                consensus = 'BUY' if buy_v >= 2 else 'SELL' if sell_v >= 2 else 'NEUTRAL'
                confidence = max((s['confidence'] for s in signals_display.values()), default=0)
        except Exception as e:
            logger.debug("V1 signals fallback failed: %s", e)
    
    data['signals'] = signals_display
    data['consensus'] = consensus
    data['confidence'] = confidence

    try:
        data['strategy_weights'] = _brain.v10.v9.v8.v7.v6.v5.auto_weighter.get_all_weights()
    except Exception as e:
        logger.debug("Strategy weights access failed: %s", e)
        data['strategy_weights'] = {}
    try:
        data['bayesian_probs'] = _brain.v10.v9.v8.v7.v6.v5.v4.bayesian.get_all_probabilities()
    except Exception as e:
        logger.debug("Bayesian probs access failed: %s", e)
        data['bayesian_probs'] = {}

    # V2 context - cached (expensive MT5 + brain chain calls)
    _v2_cache = getattr(get_dashboard_data, '_v2_cache', None)
    _v2_cache_time = getattr(get_dashboard_data, '_v2_cache_time', 0)
    if _v2_cache and (time.time() - _v2_cache_time) < 5:
        data.update(_v2_cache)
    else:
        try:
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 300)
            if rates is not None:
                df = pd.DataFrame(rates)
                _brain.v10.v9.v8.v7.v6.v5.v4.v3.v2.v1.analyzer._calc_indicators(df)
                regime_info = _brain.v10.v9.v8.v7.v6.v5.v4.v3.v2.regime.detect(df)
                data['regime'] = regime_info.get('regime', 'unknown')
                raw_adx = float(regime_info.get('adx', 0) or 0)
                data['adx'] = raw_adx if raw_adx == raw_adx else 0.0
                data['squeeze'] = bool(regime_info.get('squeeze', False))
                data['range_pct'] = regime_info.get('range_pct', 0)
                data['candle_patterns'] = [p[0] for p in _brain.v10.v9.v8.v7.v6.v5.v4.v3.v2.candles.detect(df)]
                ft, fc = _brain.v10.v9.v8.v7.v6.v5.v4.v3.v2.fractals.detect_pattern(df)
                data['fractal_trend'] = ft
                z = _brain.v10.v9.v8.v7.v6.v5.v4.v3.v2.zscore.calculate(df)
                data['z_score'] = float(z) if z is not None and not (isinstance(z, float) and z != z) else 0.0
            else:
                data['regime'] = 'unknown'; data['adx'] = 0; data['squeeze'] = False
                data['range_pct'] = 0; data['candle_patterns'] = []; data['fractal_trend'] = 'neutral'; data['z_score'] = 0
        except Exception as e:
            logger.debug("V2 context access failed: %s", e)
            data['regime'] = 'unknown'; data['adx'] = 0; data['squeeze'] = False
            data['range_pct'] = 0; data['candle_patterns'] = []; data['fractal_trend'] = 'neutral'; data['z_score'] = 0
        _v2_keys = ['regime','adx','squeeze','range_pct','candle_patterns','fractal_trend','z_score']
        get_dashboard_data._v2_cache = {k: data[k] for k in _v2_keys if k in data}
        get_dashboard_data._v2_cache_time = time.time()

    try:
        data['session'] = _brain.v10.v9.v8.v7.v6.v5.v4.v3.v2.session.get_current_session()
        data['is_kill_zone'] = _brain.v10.v9.v8.v7.v6.v5.v4.v3.v2.session.is_kill_zone()
    except Exception as e:
        logger.debug("Session access failed: %s", e)
        data['session'] = 'unknown'; data['is_kill_zone'] = False
    try:
        session_stats = _brain.v10.v9.v8.v7.v6.v5.session_memory.get_all_stats()
        data['session_wr'] = session_stats.get(data['session'], {}).get('win_rate', 50)
    except Exception as e:
        logger.debug("Session stats access failed: %s", e)
        data['session_wr'] = 50

    # V3 efficiency - safe access
    try:
        data['circuit_open'] = _brain.v10.v9.v8.v7.v6.v5.v4.v3.circuit_breaker.is_open()
        data['consec_losses'] = _brain.v10.v9.v8.v7.v6.v5.v4.v3.circuit_breaker.consecutive_losses
        data['total_breaks'] = _brain.v10.v9.v8.v7.v6.v5.v4.v3.circuit_breaker.total_breaks
    except Exception as e:
        logger.debug("Circuit breaker access failed: %s", e)
        data['circuit_open'] = False; data['consec_losses'] = 0; data['total_breaks'] = 0
    try:
        data['avg_spread'] = _brain.v10.v9.v8.v7.v6.v5.v4.v3.execution.get_avg_spread(symbol)
        data['avg_slippage'] = _brain.v10.v9.v8.v7.v6.v5.v4.v3.execution.get_avg_slippage()
    except Exception as e:
        logger.debug("Execution stats access failed: %s", e)
        data['avg_spread'] = 0; data['avg_slippage'] = 0
    try:
        data['decay_score'] = _brain.v10.v9.v8.v7.v6.v5.v4.v3.v2.decay.get_decay_score()
    except Exception as e:
        logger.debug("Decay score access failed: %s", e)
        data['decay_score'] = 1.0
    try:
        data['analysis_count'] = _brain.v10.v9.v8.v7.v6.v5.v4.v3._analysis_count
        data['skip_count'] = _brain.v10.v9.v8.v7.v6.v5.v4.v3._skip_count
    except Exception as e:
        logger.debug("Analysis count access failed: %s", e)
        data['analysis_count'] = 0; data['skip_count'] = 0
    total_a = max(data.get('analysis_count', 0), 1)
    data['skip_rate'] = data.get('skip_count', 0) / total_a * 100
    try:
        perf = _brain.v10.v9.v8.v7.v6.v5.v4.v3.profiler.call_counts.get('total_analyze', {})
        data['avg_analyze_ms'] = perf.get('total_ms', 0) / max(perf.get('count', 1), 1)
    except Exception as e:
        logger.debug("Profiler access failed: %s", e)
        data['avg_analyze_ms'] = 0

    # V4 precision - safe access
    data['divergence'] = False
    data['agreement'] = 1.0
    data['false_breakout'] = False
    data['entry_quality_total'] = 0.5
    data['entry_quality_dims'] = {}
    try:
        data['adaptive_threshold'] = _brain.v10.v9.v8.v7.v6.v5.v4.adaptive_thresholds.current_threshold
    except Exception as e:
        logger.debug("Adaptive threshold access failed: %s", e)
        data['adaptive_threshold'] = 0.55
    data['current_hour'] = datetime.now(timezone.utc).hour
    try:
        data['time_mod'] = _brain.v10.v9.v8.v7.v6.v5.v4.time_analyzer.get_hour_modifier(data['current_hour'])
        best = _brain.v10.v9.v8.v7.v6.v5.v4.time_analyzer.get_best_hours()
        data['best_hours_str'] = ', '.join(f"{h}:00({wr:.0%})" for h, wr in best[:3]) if best else 'N/A'
    except Exception as e:
        logger.debug("Time analyzer access failed: %s", e)
        data['time_mod'] = 1.0; data['best_hours_str'] = 'N/A'
    data['corr_momentum'] = 0
    try:
        corr = _brain.v10.v9.v8.v7.v6.v5.v4.corr_momentum.get_correlated_momentum(symbol)
        data['corr_momentum'] = corr.get('score', 0)
    except Exception as e:
        logger.debug("Correlation momentum access failed: %s", e)

    # V5 self-learning - safe access
    try:
        edge = _brain.v10.v9.v8.v7.v6.v5.edge_decay.detect_decay()
        data['edge_decaying'] = edge.get('decaying', False)
        data['edge_score'] = edge.get('score', 0)
        data['recent_wr'] = edge.get('recent_wr', 0.5)
    except Exception as e:
        logger.debug("Edge decay access failed: %s", e)
        data['edge_decaying'] = False; data['edge_score'] = 0; data['recent_wr'] = 0.5
    try:
        streak = _brain.v10.v9.v8.journal.get_streak_prediction()
        if streak:
            data['streak_str'] = f"{streak['current_streak']}{streak['type']} (revert: {streak['revert_likelihood']:.0%})"
        else:
            data['streak_str'] = 'N/A'
    except Exception as e:
        logger.debug("Streak prediction access failed: %s", e)
        data['streak_str'] = 'N/A'
    try:
        data['auto_weights'] = _brain.v10.v9.v8.v7.v6.v5.auto_weighter.get_all_weights()
        data['disabled_strategies'] = _brain.v10.v9.v8.v7.v6.v5.auto_weighter.get_disabled_strategies()
    except Exception as e:
        logger.debug("Auto weights access failed: %s", e)
        data['auto_weights'] = {}; data['disabled_strategies'] = []
    data['session_memory'] = session_stats if 'session_stats' in locals() else {}

    # V9 system monitoring - safe access
    try:
        sys_data = _brain.v10.v9.sys_monitor.full_check()
        data['health_score'] = _brain.v10.v9.sys_monitor.get_health_score()
        data['cpu_overall'] = sys_data['cpu']['overall']
        data['cpu_avg'] = _brain.v10.v9.sys_monitor.cpu.get_average()
        data['cpu_peak'] = _brain.v10.v9.sys_monitor.cpu.get_peak()
        data['cpu_trend'] = _brain.v10.v9.sys_monitor.cpu.get_trend()
        data['cpu_cores'] = sys_data['cpu']['core_count']
        data['cpu_freq'] = sys_data['cpu']['freq_current']
        data['mem_percent'] = sys_data['memory']['percent']
        data['mem_used'] = sys_data['memory']['used_gb']
        data['mem_total'] = sys_data['memory']['total_gb']
        data['mem_avail'] = sys_data['memory']['available_gb']
        data['mem_trend'] = _brain.v10.v9.sys_monitor.memory.get_trend()
        data['swap_percent'] = sys_data['memory']['swap_percent']
        data['mt5_running'] = sys_data['processes']['mt5_running']
        data['mt5_cpu'] = sys_data['processes']['mt5_cpu']
        data['mt5_mem'] = sys_data['processes']['mt5_mem']
        data['python_running'] = sys_data['processes']['python_running']
        data['python_cpu'] = sys_data['processes']['python_cpu']
        data['python_mem'] = sys_data['processes']['python_mem']
        data['disk'] = sys_data['disk']
        data['alerts'] = _brain.v10.v9.sys_monitor.get_alerts(5)
        progress = _brain.v10.v9.progress.get_progress()
        data['session_hours'] = progress['session_duration_hours']
        data['session_trades'] = progress['session_trades']
        data['session_wr'] = progress['session_win_rate']
        data['session_pnl'] = progress['session_pnl']
        data['session_dd'] = progress['session_max_drawdown']
        data['trades_per_hour'] = progress['trades_per_hour']
        tp = progress.get('target_progress', {})
        data['target_trades'] = tp.get('trades', '0/20')
        data['target_trades_pct'] = tp.get('trades_pct', 0)
        data['target_profit'] = tp.get('profit', '$0/$100')
        data['target_profit_pct'] = tp.get('profit_pct', 0)
    except Exception as e:
        data['health_score'] = 0
        data['cpu_overall'] = 0; data['cpu_avg'] = 0; data['cpu_peak'] = 0; data['cpu_trend'] = 'unknown'
        data['cpu_cores'] = 0; data['cpu_freq'] = 0
        data['mem_percent'] = 0; data['mem_used'] = 0; data['mem_total'] = 0; data['mem_avail'] = 0; data['mem_trend'] = 'unknown'
        data['swap_percent'] = 0
        data['mt5_running'] = False; data['mt5_cpu'] = 0; data['mt5_mem'] = 0
        data['python_running'] = False; data['python_cpu'] = 0; data['python_mem'] = 0
        data['disk'] = {}; data['alerts'] = []
        data['session_hours'] = 0; data['session_trades'] = 0; data['session_wr'] = 0
        data['session_pnl'] = 0; data['session_dd'] = 0; data['trades_per_hour'] = 0
        data['target_trades'] = '0/20'; data['target_trades_pct'] = 0
        data['target_profit'] = '$0/$100'; data['target_profit_pct'] = 0

    # Watchlist — read from shared_state (populated by SymbolAnalyzer threads)
    watchlist = []
    try:
        import shared_state
        all_analysis = shared_state.get_all_analysis()
        for sym in SCAN_SYMBOLS:
            analysis = all_analysis.get(sym)
            if analysis and analysis.get("bid", 0) > 0:
                watchlist.append({
                    'symbol': sym,
                    'bid': analysis.get("bid", 0),
                    'ask': analysis.get("ask", 0),
                    'spread': analysis.get("spread", 0),
                    'atr': 0,
                    'high_vol': False,
                    'trend': analysis.get("direction", "NEUTRAL"),
                })
            else:
                watchlist.append({'symbol': sym, 'bid': 0, 'ask': 0, 'spread': 0, 'atr': 0, 'high_vol': False, 'trend': 'NEUTRAL'})
    except Exception:
        for sym in SCAN_SYMBOLS:
            watchlist.append({'symbol': sym, 'bid': 0, 'ask': 0, 'spread': 0, 'atr': 0, 'high_vol': False, 'trend': 'NEUTRAL'})
    data['watchlist'] = watchlist

    # Live analysis status — read from shared_state (written by SymbolAnalyzer threads)
    analysis_status = []
    try:
        import shared_state
        all_analysis = shared_state.get_all_analysis()
        symbols = shared_state.get_symbols()

        # If no symbols registered yet, fall back to SCAN_SYMBOLS
        if not symbols:
            symbols = SCAN_SYMBOLS

        for sym in symbols:
            cached = all_analysis.get(sym)
            if cached:
                analysis_status.append(cached)
            else:
                # Symbol not yet analyzed — show placeholder
                tick = mt5.symbol_info_tick(sym)
                analysis_status.append({
                    "symbol": sym,
                    "tick_time": "--:--:--",
                    "tick_age_ms": 0,
                    "bid": tick.bid if tick else 0,
                    "ask": tick.ask if tick else 0,
                    "spread": round((tick.ask - tick.bid) / mt5.symbol_info(sym).point) if tick and mt5.symbol_info(sym) else 0,
                    "action": "hold",
                    "direction": "NEUTRAL",
                    "confidence": 0,
                    "method": "N/A",
                    "regime": "unknown",
                    "session": "unknown",
                    "analysis_ms": 0,
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "market_closed": True,
                })
    except Exception as e:
        logger.debug("Analysis status read failed: %s", e)

    data['analysis_status'] = analysis_status
    data['analysis_active_count'] = sum(1 for a in analysis_status if not a.get('market_closed', True))
    data['analysis_closed_count'] = sum(1 for a in analysis_status if a.get('market_closed', True))
    data['analysis_signal_count'] = sum(1 for a in analysis_status if a.get('action') == 'trade')
    data['analysis_avg_ms'] = round(sum(a.get('analysis_ms', 0) for a in analysis_status) / max(len(analysis_status), 1), 1)

    # V11 meta-brain status
    try:
        v11_status = _brain.v11.get_status()
        data['v11'] = {
            "method": v11_status.get("current_method", "TECHNICAL"),
            "secondary_method": v11_status.get("secondary_method", None),
            "config": v11_status.get("config", {}),
            "method_scores": v11_status.get("method_scores", {}),
            "method_performance": v11_status.get("method_performance", {}),
        }
    except Exception as e:
        logger.debug("V11 status access failed: %s", e)
        data['v11'] = {
            "method": "TECHNICAL",
            "secondary_method": None,
            "config": {"sl_atr_mult": 1.5, "tp_atr_mult": 2.5, "risk_per_trade": 1.0},
            "method_scores": {},
            "method_performance": {},
        }

    # History
    try:
        all_deals = mt5.history_deals_get(now - timedelta(days=30), now, group="*")
    except Exception as e:
        logger.debug("History fetch failed: %s", e)
        all_deals = None
    history = []
    for d in (all_deals or []):
        if is_system_magic(d.magic) and d.entry == mt5.DEAL_ENTRY_OUT:
            history.append({'time': datetime.fromtimestamp(d.time).strftime("%m-%d %H:%M"), 'symbol': d.symbol, 'type': d.type, 'volume': d.volume, 'price': d.price, 'profit': d.profit, 'comment': d.comment})
    data['history'] = history[-20:]

    # Sanitize all values for JSON serialization (convert numpy types to native Python)
    return _sanitize(data)


def _sanitize(obj):
    """Recursively convert numpy/enum types to native Python types for JSON."""
    if isinstance(obj, dict):
        return {_sanitize(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, Enum):
        return str(obj.value)
    if isinstance(obj, _np.bool_):
        return bool(obj)
    if isinstance(obj, _np.integer):
        return int(obj)
    if isinstance(obj, _np.floating):
        v = float(obj)
        return 0.0 if v != v else v
    if isinstance(obj, _np.ndarray):
        return obj.tolist()
    return obj


import json as _json
import numpy as _np

class NumpyEncoder(_json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, _Enum):
            return str(obj.value)
        if isinstance(obj, (_np.bool_,)):
            return bool(obj)
        if isinstance(obj, (_np.integer,)):
            return int(obj)
        if isinstance(obj, (_np.floating,)):
            v = float(obj)
            return 0.0 if v != v else v
        if isinstance(obj, _np.ndarray):
            return obj.tolist()
        return super().default(obj)


@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/api/data')
def api_data():
    return jsonify(get_dashboard_data())


@app.route('/api/debug')
def api_debug():
    import shared_state
    acct = mt5.account_info()
    return jsonify({
        "mt5_connected": mt5.terminal_info() is not None,
        "account": {
            "login": acct.login if acct else None,
            "balance": acct.balance if acct else 0,
        },
        "symbols": shared_state.get_symbols(),
        "analysis_count": len(shared_state.get_all_analysis()),
        "analysis_sample": list(shared_state.get_all_analysis().values())[:2] if shared_state.get_all_analysis() else [],
    })


@app.route('/health')
def health():
    import time
    import mt5
    terminal_ok = mt5.terminal_info() is not None
    account = mt5.account_info()
    return jsonify({
        "status": "ok" if terminal_ok else "degraded",
        "mt5_connected": terminal_ok,
        "equity": account.equity if account else 0,
        "balance": account.balance if account else 0,
        "uptime_seconds": int(time.time() - _start_time) if '_start_time' in globals() else 0,
    })


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8050, debug=False)
