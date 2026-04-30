import React, { useEffect, useMemo, useRef, useState } from 'react';

const T = {
  bg:'#f4f6fb', surface0:'#ffffff', surface1:'#fafbff', surface2:'#ffffff', surface3:'#eef0f7', surface4:'#d8dde8',
  outline:'#b8c0d4', outlineSoft:'#dde2ee',
  text:'#1a1d2e', textDim:'#4a5170', textMuted:'#8b92a8',
  primary:'#10b981', primaryBr:'#059669',
  amber:'#f97316', amberBr:'#ea580c',
  red:'#f43f5e', redBr:'#e11d48', blue:'#2563eb', purple:'#8b5cf6',
  font:'"Times New Roman", Times, serif',
  mono:'"Courier New", Courier, monospace',
};

const H_INFO = {
  'FIFO':           { color: '#64748b', short: 'First In, First Out',     formula: 'Oldest job first',          when: 'Trivial load, end-of-shift' },
  'Priority-EDD':   { color: '#a78bfa', short: 'Earliest Due Date',       formula: 'Sort by deadline ↑',        when: 'Express-heavy, tight SLAs' },
  'Critical Ratio': { color: T.amberBr, short: 'Critical Ratio',          formula: 'CR = slack / remaining',    when: 'Breakdowns, mixed urgency' },
  'ATC':            { color: T.blue,    short: 'Apparent Tardiness Cost', formula: 'ATC(K=2.0) weighted score', when: 'High load, balanced mix' },
  'WSPT':           { color: T.primaryBr, short: 'Weighted Shortest Proc.', formula: 'WSPT = w / proc_time',    when: 'Short-job backlog, throughput' },
  'Slack':          { color: T.redBr,   short: 'Minimum Slack',           formula: 'Slack = due − now − proc',  when: 'Recovery, imminent deadlines' },
};

const H_KEY_TO_LABEL = { fifo:'FIFO', priority_edd:'Priority-EDD', critical_ratio:'Critical Ratio', atc:'ATC', wspt:'WSPT', slack:'Slack' };

const PRESETS = [
  { id: 'balanced',  preset: null,            label: 'Balanced Mix',        desc: 'Custom mode — choose any baseline; mixed warehouse load' },
  { id: 'breakdown', preset: 'critical_ratio',label: 'Station Breakdowns',  desc: 'Frequent breakdowns — Critical-Ratio is the static-best baseline' },
  { id: 'express',   preset: 'priority_edd',  label: 'Express-Heavy',       desc: 'Tight deadlines + express orders — Priority-EDD baseline' },
  { id: 'overload',  preset: 'atc',           label: 'Heavy Load',          desc: 'Heavy sustained load — ATC baseline' },
  { id: 'wspt',      preset: 'wspt',          label: 'Short Job Mix',       desc: 'Many short jobs, loose deadlines — WSPT baseline' },
  { id: 'slack',     preset: 'slack',         label: 'Tight Deadlines',     desc: 'Recovery mode, very tight SLAs — Slack baseline' },
];

function convertEvalLog(backendLog) {
  if (!Array.isArray(backendLog)) return [];
  const out = [];
  let prevKey = 'fifo';
  for (const e of backendLog) {
    const toKey = e.heuristic || prevKey;
    const fromKey = prevKey;
    let type = 'hold';
    if (e.reason && String(e.reason).startsWith('guardrail')) type = 'guardrail';
    else if (e.reason === 'hysteresis_blocked') type = 'blocked';
    else if (e.switched || toKey !== fromKey) type = 'switch';
    out.push({
      t: Math.round(Number(e.time) || 0),
      from: H_KEY_TO_LABEL[fromKey] || 'FIFO',
      to: H_KEY_TO_LABEL[toKey] || 'FIFO',
      type,
      conf: type === 'guardrail' ? null : (typeof e.confidence === 'number' ? e.confidence : null),
      reason: e.reason || 'ml_decision',
      plain: e.plainEnglish || '',
    });
    prevKey = toKey;
  }
  return out;
}

function snapToZones(snap) {
  if (!snap) return null;
  const active = snap.zoneActiveCounts || [];
  const queue = snap.zoneQueueLengths || [];
  return Array.from({ length: 8 }, (_, i) => {
    const a = active[i] || 0;
    const q = queue[i] || 0;
    const util = a > 0 ? Math.min(0.95, 0.55 + q * 0.04) : (q > 0 ? 0.3 : 0.12);
    return { util, queue: q, broken: 0 };
  });
}

function emptyMetrics() {
  return { completed: 0, totalTardiness: 0, slaBreachRate: 0, avgCycleTime: 0, throughput: 0, jobsPerHour: 0 };
}

function pctDelta(a, b) {
  if (!b || b === 0) return null;
  return ((a - b) / b) * 100;
}

// SVG icon paths sized for a 24×24 viewBox; rendered inline with transforms in ShopFloor
const ICON_PATHS = {
  receiving: <g fill="none" strokeWidth="1.8"><path d="M3 9l9-5 9 5v11H3z"/><path d="M3 14h18"/></g>,
  cart:      <g fill="none" strokeWidth="1.8"><circle cx="9" cy="20" r="1.5"/><circle cx="17" cy="20" r="1.5"/><path d="M3 4h2l2.5 11h11l2-8H6"/></g>,
  wrench:    <g fill="none" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M14.7 6.3a4 4 0 00-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 005.4-5.4l-2.5 2.5-2.5-2.5z"/></g>,
  qc:        <g fill="none" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/></g>,
  pack:      <g fill="none" strokeWidth="1.8" strokeLinejoin="round"><path d="M3 7l9-4 9 4-9 4z"/><path d="M3 7v10l9 4 9-4V7"/><path d="M12 11v10"/></g>,
  dispatch:  <g fill="none" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="1" y="6" width="14" height="11"/><path d="M15 9h4l3 4v4h-7"/><circle cx="6" cy="19" r="1.8"/><circle cx="18" cy="19" r="1.8"/></g>,
};

// Vibrant zone palette — distinct color per stage so the flow is easy to read
const ZONE_PALETTE = {
  receiving: { idle:'#94a3b8', hot:'#06b6d4', label:'#0891b2' },  // cyan
  pickingA:  { idle:'#94a3b8', hot:'#10b981', label:'#059669' },  // emerald
  pickingB:  { idle:'#94a3b8', hot:'#84cc16', label:'#65a30d' },  // lime
  valueAdd:  { idle:'#94a3b8', hot:'#a855f7', label:'#9333ea' },  // purple
  qc:        { idle:'#94a3b8', hot:'#3b82f6', label:'#2563eb' },  // blue
  pack:      { idle:'#94a3b8', hot:'#f59e0b', label:'#d97706' },  // amber
  dispatch:  { idle:'#94a3b8', hot:'#ec4899', label:'#db2777' },  // pink
};

function Sparkline({ color = T.primary, seed = 0 }) {
  const pts = Array.from({ length: 12 }, (_, i) => {
    const v = 8 + Math.sin(i * 0.7 + seed) * 3 + Math.cos(i * 0.4 + seed * 1.3) * 2;
    return [i * 5, 14 - v];
  });
  const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0]},${p[1]}`).join(' ');
  return (
    <svg width="60" height="14" viewBox="0 0 60 14" style={{ opacity: 0.55 }}>
      <path d={`${d} L60,14 L0,14 Z`} fill={color} opacity="0.18" />
      <path d={d} fill="none" stroke={color} strokeWidth="1.2" />
    </svg>
  );
}

function ShopFloor({ zoneStates }) {
  const NODES = [
    { id: 'receiving', label: 'RECEIVING', icon: 'receiving', x: 30,  y: 80,  zi: 0 },
    { id: 'pickingA',  label: 'PICKING A', icon: 'cart',      x: 165, y: 14,  zi: 1 },
    { id: 'pickingB',  label: 'PICKING B', icon: 'cart',      x: 165, y: 146, zi: 2 },
    { id: 'valueAdd',  label: 'VALUE-ADD', icon: 'wrench',    x: 295, y: 80,  zi: 5 },
    { id: 'qc',        label: 'QC',        icon: 'qc',        x: 410, y: 80,  zi: 3 },
    { id: 'pack',      label: 'PACK',      icon: 'pack',      x: 525, y: 80,  zi: 4 },
    { id: 'dispatch',  label: 'DISPATCH',  icon: 'dispatch',  x: 660, y: 80,  zi: 7 },
  ];
  const W = 770, H = 244;
  const NW = 92, NH = 80;

  const c = (n, side) => {
    if (side === 'r') return { x: n.x + NW, y: n.y + NH / 2 };
    if (side === 'l') return { x: n.x,      y: n.y + NH / 2 };
    return { x: n.x + NW / 2, y: n.y + NH / 2 };
  };
  const m = Object.fromEntries(NODES.map((n) => [n.id, n]));
  const lines = [
    [c(m.receiving, 'r'), c(m.pickingA, 'l'), 'pickingA'],
    [c(m.receiving, 'r'), c(m.pickingB, 'l'), 'pickingB'],
    [c(m.pickingA,  'r'), c(m.valueAdd, 'l'), 'valueAdd'],
    [c(m.pickingB,  'r'), c(m.valueAdd, 'l'), 'valueAdd'],
    [c(m.valueAdd,  'r'), c(m.qc,       'l'), 'qc'],
    [c(m.qc,        'r'), c(m.pack,     'l'), 'pack'],
    [c(m.pack,      'r'), c(m.dispatch, 'l'), 'dispatch'],
  ];

  function status(node) {
    const pal = ZONE_PALETTE[node.id] || { idle: T.outlineSoft, hot: T.primary, label: T.text };
    const s = zoneStates?.[node.zi];
    if (!s) return { color: pal.idle, glow: false, queue: 0, kind: 'idle', pal };
    if (s.broken > 0) return { color: T.red,   glow: true, queue: s.queue, kind: 'down',   pal };
    if (s.queue > 4)  return { color: T.amber, glow: true, queue: s.queue, kind: 'queued', pal };
    if (s.util > 0.4) return { color: pal.hot, glow: true, queue: s.queue, kind: 'active', pal };
    return { color: pal.idle, glow: false, queue: s.queue, kind: 'idle', pal };
  }

  return (
    <div style={{ width: '100%', background: T.surface0, padding: '12px 12px 28px', position: 'relative', boxSizing: 'border-box' }}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
           style={{ display: 'block', width: '100%', height: 'auto', maxHeight: H, overflow: 'visible' }}>
        <defs>
          {Object.entries(ZONE_PALETTE).map(([k, p]) => (
            <linearGradient key={k} id={`g-${k}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={p.hot} stopOpacity="0.18" />
              <stop offset="100%" stopColor={p.hot} stopOpacity="0.04" />
            </linearGradient>
          ))}
        </defs>

        {/* Connectors with vibrant downstream color */}
        {lines.map((l, i) => {
          const downPal = ZONE_PALETTE[l[2]] || { hot: T.outline };
          return (
            <path key={i}
                  d={`M${l[0].x},${l[0].y} C${(l[0].x+l[1].x)/2},${l[0].y} ${(l[0].x+l[1].x)/2},${l[1].y} ${l[1].x},${l[1].y}`}
                  stroke={downPal.hot} strokeWidth="2" fill="none" strokeOpacity="0.45"
                  markerEnd="url(#arrow)" />
          );
        })}
        <defs>
          <marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <polygon points="0 0, 6 3, 0 6" fill={T.outline} />
          </marker>
        </defs>

        {NODES.map((n) => {
          const st = status(n);
          const stroke = st.color;
          return (
            <g key={n.id} transform={`translate(${n.x},${n.y})`}>
              {st.glow && (
                <rect x="-3" y="-3" width={NW + 6} height={NH + 6} rx="11"
                      fill="none" stroke={stroke} strokeWidth="1" opacity="0.35" />
              )}
              <rect width={NW} height={NH} rx="9"
                    fill={`url(#g-${n.id})`} stroke={stroke}
                    strokeWidth={st.glow ? 2.4 : 1.4} />
              {/* icon */}
              <g transform={`translate(${NW/2 - 12},10) scale(1)`} stroke={st.pal.label} fill="none">
                {ICON_PATHS[n.icon]}
              </g>
              {/* label */}
              <text x={NW/2} y={48} textAnchor="middle"
                    fontFamily={T.font} fontSize="10" fontWeight="700"
                    fill={st.pal.label} style={{ letterSpacing: '0.06em' }}>
                {n.label}
              </text>
              {/* mini bar / sparkline area */}
              <g transform={`translate(${(NW-60)/2},58)`}>
                {Array.from({length: 12}).map((_, i) => {
                  const v = 4 + Math.abs(Math.sin(i * 0.7 + n.zi)) * 8;
                  return <rect key={i} x={i*5} y={12 - v} width="3" height={v} rx="1" fill={st.pal.hot} opacity={st.glow ? 0.85 : 0.35} />;
                })}
              </g>
              {/* queue pip */}
              {st.queue > 0 && (
                <g>
                  <circle cx={NW - 6} cy="6" r="11"
                          fill={st.kind === 'down' ? T.red : st.kind === 'queued' ? T.amber : st.pal.hot} />
                  <text x={NW - 6} y="10" textAnchor="middle"
                        fontFamily={T.font} fontSize="11" fontWeight="800" fill="#fff">{st.queue}</text>
                </g>
              )}
            </g>
          );
        })}
      </svg>

      <div style={{ position: 'absolute', right: 18, bottom: 8, display: 'flex', gap: 10, fontFamily: T.font, fontSize: 12, fontWeight: 700 }}>
        <span style={{ color: '#10b981' }}>● Active</span>
        <span style={{ color: '#f59e0b' }}>● Queued</span>
        <span style={{ color: '#f43f5e' }}>● Down</span>
      </div>
    </div>
  );
}

function KPI({ label, value, delta, deltaGood, accent }) {
  const dColor = delta == null ? T.textMuted : (deltaGood ? T.primaryBr : T.redBr);
  const dStr = delta == null ? '' : `(${delta > 0 ? '+' : ''}${delta.toFixed(1)}%)`;
  return (
    <div style={{ flex: 1, padding: '10px 6px 12px', borderTop: `2px solid ${accent || T.surface3}`, position: 'relative' }}>
      <div style={{ fontFamily: T.font, fontSize: 10, fontWeight: 600, color: T.textMuted, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 4 }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span style={{ fontFamily: T.font, fontSize: 20, fontWeight: 800, color: T.text, lineHeight: 1 }}>{value}</span>
        {delta != null && (
          <span style={{ fontFamily: T.font, fontSize: 11, fontWeight: 700, color: dColor }}>{dStr}</span>
        )}
      </div>
    </div>
  );
}

function ArmCard({ title, tag, accent, snap, otherSnap, isDahs }) {
  const m = snap?.metrics || emptyMetrics();
  const o = otherSnap?.metrics || emptyMetrics();
  const onTime = (1 - (m.slaBreachRate || 0)) * 100;
  const onTimeOther = (1 - (o.slaBreachRate || 0)) * 100;
  const queueTotal = (snap?.zoneQueueLengths || []).reduce((a, b) => a + b, 0);
  const activeTotal = (snap?.zoneActiveCounts || []).reduce((a, b) => a + b, 0);
  const zones = snapToZones(snap);

  const stats = [
    { label: 'Completed', value: m.completed || 0, delta: pctDelta(m.completed, o.completed), deltaGood: (m.completed >= o.completed) },
    { label: 'On-Time %', value: `${onTime.toFixed(1)}%`, delta: onTime - onTimeOther, deltaGood: onTime >= onTimeOther },
    { label: 'Σ Tardiness', value: `${Math.round(m.totalTardiness || 0)}m`, delta: pctDelta(m.totalTardiness, o.totalTardiness), deltaGood: (m.totalTardiness <= o.totalTardiness) },
    { label: 'Throughput', value: `${(m.jobsPerHour || 0).toFixed(0)}/h`, delta: null },
    { label: 'In Queue', value: queueTotal, delta: null },
    { label: 'Processing', value: activeTotal, delta: null },
  ];

  return (
    <div style={{ flexShrink: 0, background: T.surface1, border: `1px solid ${accent}66`, borderRadius: 6, overflow: 'hidden', boxShadow: `inset 0 0 0 1px ${accent}10` }}>
      <div style={{ padding: '10px 16px', display: 'flex', alignItems: 'center', gap: 10, borderBottom: `1px solid ${T.outlineSoft}`, background: `linear-gradient(90deg, ${accent}14, transparent 60%)`, flexWrap: 'wrap' }}>
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: accent, boxShadow: `0 0 8px ${accent}` }} />
        <span style={{ fontFamily: T.font, fontSize: 14, fontWeight: 700, color: accent, letterSpacing: '0.02em' }}>{title}</span>
        <span style={{ fontFamily: T.font, fontSize: 12, color: T.textDim }}>· {tag}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(90px, 1fr))', borderBottom: `1px solid ${T.outlineSoft}`, padding: '0 8px' }}>
        {stats.map((s, i) => <KPI key={i} {...s} accent={isDahs && s.deltaGood ? accent : undefined} />)}
      </div>
      <ShopFloor zoneStates={zones} />
    </div>
  );
}

function HeuristicTimeline({ log, currentTime, simDone }) {
  const [hovered, setHovered] = useState(null);
  const barRef = useRef(null);

  const segments = [];
  if (log && log.length) {
    let prev = { t: 0, h: log[0]?.from || 'FIFO' };
    log.forEach((entry) => {
      if (entry.t > prev.t) segments.push({ from: prev.t, to: entry.t, h: prev.h });
      prev = { t: entry.t, h: entry.to };
    });
    if (prev.t < 600) segments.push({ from: prev.t, to: 600, h: prev.h });
  }

  function getEntryForSeg(seg) {
    return log.find((e) => e.t === seg.from && e.to === seg.h) || null;
  }

  const typeColors = { switch: T.blue, hold: T.primary, blocked: T.amber, guardrail: T.red };
  const typeLabels = { switch: '↔ SWITCHED', hold: '— HELD', blocked: '⚡ BLOCKED', guardrail: '🛡 GUARDRAIL' };

  function handleSegHover(e, segIdx) {
    if (!simDone) return;
    const rect = barRef.current.getBoundingClientRect();
    setHovered({ segIdx, x: e.clientX - rect.left, y: e.clientY - rect.top });
  }

  const hovSeg = hovered !== null ? segments[hovered.segIdx] : null;
  const hovEntry = hovSeg ? getEntryForSeg(hovSeg) : null;
  const hovInfo = hovSeg ? (H_INFO[hovSeg.h] || {}) : {};

  return (
    <div style={{ flexShrink: 0, padding: '14px 20px', background: T.surface1, borderRadius: 6, border: `1px solid ${T.outlineSoft}`, position: 'relative' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, fontFamily: T.font, fontSize: 11, fontWeight: 600, color: T.textDim, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        <span>DAHS Heuristic Timeline — 600 min Shift {simDone && <span style={{ color: T.primary, marginLeft: 8, textTransform: 'none', letterSpacing: 0 }}>· hover tiles to inspect</span>}</span>
        <span style={{ fontFamily: T.mono, color: T.text }}>{currentTime > 0 ? `t = ${currentTime}m` : '—'}</span>
      </div>

      <div ref={barRef} style={{ position: 'relative', height: 36, borderRadius: 4, overflow: 'visible', background: T.surface0, display: 'flex', cursor: simDone ? 'crosshair' : 'default' }}
        onMouseLeave={() => setHovered(null)}>
        <div style={{ display: 'flex', width: '100%', borderRadius: 4, overflow: 'hidden' }}>
          {segments.length === 0 ? (
            <div style={{ width: '100%', height: '100%', background: T.surface2 }} />
          ) : segments.map((seg, i) => {
            const info = H_INFO[seg.h] || {};
            const pct = ((seg.to - seg.from) / 600) * 100;
            const isHov = hovered?.segIdx === i;
            return (
              <div key={i}
                style={{ width: `${pct}%`, background: info.color, opacity: isHov ? 1 : 0.85, position: 'relative', borderRight: `1px solid ${T.surface0}`, transition: 'opacity 0.15s', flexShrink: 0 }}
                onMouseEnter={(e) => handleSegHover(e, i)}
                onMouseMove={(e) => handleSegHover(e, i)}>
                {pct > 6 && (
                  <span style={{ position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', fontFamily: T.font, fontSize: 9, fontWeight: 700, color: '#0a0d1d', whiteSpace: 'nowrap', pointerEvents: 'none', letterSpacing: '0.04em' }}>
                    {seg.h.split(' ')[0]}
                  </span>
                )}
                {isHov && <div style={{ position: 'absolute', inset: 0, border: `2px solid ${T.text}`, borderRadius: 2, pointerEvents: 'none' }} />}
              </div>
            );
          })}
        </div>

        {currentTime > 0 && (
          <div style={{ position: 'absolute', left: `${(currentTime / 600) * 100}%`, top: -3, bottom: -3, width: 2, background: T.primaryBr, boxShadow: `0 0 10px ${T.primaryBr}`, zIndex: 10, transition: 'left 0.3s', borderRadius: 1 }} />
        )}

        {simDone && hovered && hovSeg && (
          <div style={{
            position: 'absolute', zIndex: 100,
            left: Math.min(hovered.x + 8, 420), top: 44,
            background: T.surface2, border: `1px solid ${hovInfo.color || T.outline}66`,
            borderRadius: 8, padding: '11px 14px', minWidth: 230, maxWidth: 290,
            boxShadow: `0 12px 36px rgba(0,0,0,0.7), 0 0 0 1px ${hovInfo.color || T.outline}30`,
            pointerEvents: 'none',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 6 }}>
              <div style={{ width: 10, height: 10, borderRadius: '50%', background: hovInfo.color, boxShadow: `0 0 8px ${hovInfo.color}` }} />
              <span style={{ fontFamily: T.font, fontSize: 13, fontWeight: 700, color: T.text }}>{hovSeg.h}</span>
              <span style={{ fontFamily: T.mono, fontSize: 10, color: T.textMuted, marginLeft: 'auto' }}>t={hovSeg.from}–{hovSeg.to}m</span>
            </div>
            {hovEntry && (
              <>
                <div style={{ display: 'flex', gap: 6, marginBottom: 6, alignItems: 'center' }}>
                  <span style={{ fontFamily: T.font, fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 3, background: `${typeColors[hovEntry.type]}25`, color: typeColors[hovEntry.type], letterSpacing: '0.06em' }}>
                    {typeLabels[hovEntry.type]}
                  </span>
                  {hovEntry.conf !== null && (
                    <span style={{ fontFamily: T.mono, fontSize: 10, color: T.textDim }}>{(hovEntry.conf * 100).toFixed(0)}% conf.</span>
                  )}
                </div>
                <p style={{ fontFamily: T.font, fontSize: 11, color: T.textDim, lineHeight: 1.55, margin: 0 }}>{hovEntry.plain}</p>
              </>
            )}
            <div style={{ marginTop: 9, paddingTop: 7, borderTop: `1px solid ${T.outlineSoft}`, fontFamily: T.font, fontSize: 10, color: T.textMuted }}>
              {hovInfo.formula} · {hovInfo.short}
            </div>
          </div>
        )}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontFamily: T.mono, fontSize: 10, color: T.textMuted }}>
        {[0, 100, 200, 300, 400, 500, 600].map((t) => <span key={t}>{t}</span>)}
      </div>
    </div>
  );
}

function ComparisonPanel({ dahsSnap, baseSnap, baselineLabel }) {
  const dm = dahsSnap?.metrics || emptyMetrics();
  const bm = baseSnap?.metrics || emptyMetrics();

  const rows = [
    { label: 'Σ Tardiness',  unit: 'm', dahs: Math.round(dm.totalTardiness || 0), base: Math.round(bm.totalTardiness || 0), higherBetter: false },
    { label: 'Jobs Processed', unit: '', dahs: dm.completed || 0, base: bm.completed || 0, higherBetter: true },
    { label: 'SLA Breaches',   unit: '', dahs: Math.round((dm.slaBreachRate || 0) * (dm.completed || 0)), base: Math.round((bm.slaBreachRate || 0) * (bm.completed || 0)), higherBetter: false },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {rows.map((r, i) => {
        const dahsWins = r.higherBetter ? r.dahs > r.base : r.dahs < r.base;
        const winValue = dahsWins ? r.dahs : r.base;
        const max = Math.max(r.dahs, r.base, 1);
        const pctD = (r.dahs / max) * 100;
        const pctB = (r.base / max) * 100;
        return (
          <div key={i}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
              <span style={{ fontFamily: T.font, fontSize: 11, fontWeight: 600, color: T.textDim, letterSpacing: '0.07em', textTransform: 'uppercase' }}>{r.label}:</span>
              <span style={{ fontFamily: T.font, fontSize: 12, fontWeight: 700, color: T.primaryBr }}>
                {winValue}{r.unit} <span style={{ color: T.textMuted, fontWeight: 600 }}>(wins)</span>
              </span>
            </div>
            <div style={{ marginBottom: 4 }}>
              <div style={{ fontFamily: T.font, fontSize: 11, fontWeight: 700, color: dahsWins ? T.primaryBr : T.textMuted, marginBottom: 3 }}>DAHS</div>
              <div style={{ height: 6, background: T.surface3, borderRadius: 9999, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${pctD}%`, background: dahsWins ? T.primary : T.surface4, borderRadius: 9999, transition: 'width 0.6s', boxShadow: dahsWins ? `0 0 8px ${T.primary}80` : 'none' }} />
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontFamily: T.font, fontSize: 11, color: T.textMuted }}>
              <span>DAHS <span style={{ color: T.text, fontFamily: T.mono, fontWeight: 700 }}>{r.dahs}{r.unit}</span></span>
              <span>{(baselineLabel || '').split(' ')[0]} <span style={{ color: T.text, fontFamily: T.mono, fontWeight: 700 }}>{r.base}{r.unit}</span></span>
            </div>
            <div style={{ height: 4, background: T.surface3, borderRadius: 9999, overflow: 'hidden', marginTop: 3 }}>
              <div style={{ height: '100%', width: `${pctB}%`, background: T.surface4, borderRadius: 9999 }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ActiveHeuristicPanel({ entry, switchCount }) {
  const h = entry ? entry.to : 'FIFO';
  const info = H_INFO[h] || H_INFO['FIFO'];
  const [flash, setFlash] = useState(false);
  const prevH = useRef(h);
  useEffect(() => {
    if (prevH.current !== h) {
      setFlash(true);
      const id = setTimeout(() => setFlash(false), 600);
      prevH.current = h;
      return () => clearTimeout(id);
    }
  }, [h]);

  const typeColors = { switch: T.blue, hold: T.primary, blocked: T.amber, guardrail: T.red };
  const typeLabels = { switch: '↔ SWITCHED', hold: '— HELD', blocked: '⚡ BLOCKED', guardrail: '🛡 GUARDRAIL' };

  return (
    <div style={{ background: T.surface1, border: `1px solid ${info.color}44`, borderRadius: 6, padding: '14px 14px', display: 'flex', flexDirection: 'column', gap: 11, boxShadow: flash ? `0 0 22px ${info.color}55` : `inset 0 0 0 1px ${info.color}10`, transition: 'box-shadow 0.4s' }}>
      <div>
        <div style={{ fontFamily: T.font, fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: T.textMuted, marginBottom: 5 }}>DAHS Active Heuristic</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div style={{ width: 11, height: 11, borderRadius: '50%', background: info.color, boxShadow: `0 0 10px ${info.color}` }} />
          <span style={{ fontFamily: T.font, fontSize: 20, fontWeight: 800, color: T.text, lineHeight: 1 }}>{h}</span>
        </div>
        <div style={{ fontFamily: T.font, fontSize: 11, color: T.textDim, marginTop: 3 }}>{info.short}</div>
      </div>
      <div style={{ background: T.surface0, borderRadius: 4, padding: '8px 11px', border: `1px solid ${T.outlineSoft}` }}>
        <div style={{ fontFamily: T.font, fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: T.textMuted, marginBottom: 3 }}>Formula</div>
        <code style={{ fontFamily: T.mono, fontSize: 11, color: info.color }}>{info.formula}</code>
      </div>
      {entry && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
            <span style={{ fontFamily: T.font, fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 3, background: `${typeColors[entry.type]}25`, color: typeColors[entry.type], letterSpacing: '0.06em' }}>
              {typeLabels[entry.type] || entry.type}
            </span>
            <span style={{ fontFamily: T.mono, fontSize: 10, color: T.textMuted }}>t = {entry.t}m</span>
          </div>
          <p style={{ fontFamily: T.font, fontSize: 11, color: T.textDim, lineHeight: 1.55, margin: 0 }}>{entry.plain}</p>
        </div>
      )}
      {entry && entry.conf !== null && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: T.font, fontSize: 10, fontWeight: 600, color: T.textMuted, marginBottom: 4 }}>
            <span>Confidence</span><span style={{ color: info.color }}>{(entry.conf * 100).toFixed(0)}%</span>
          </div>
          <div style={{ height: 5, background: T.surface3, borderRadius: 9999 }}>
            <div style={{ height: 5, width: `${entry.conf * 100}%`, background: `linear-gradient(90deg,${info.color}aa,${info.color})`, borderRadius: 9999, transition: 'width 0.5s' }} />
          </div>
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 7 }}>
        {[{ label: 'Switches', val: switchCount }, { label: 'Best for', val: info.when.split(',')[0] }].map((s, i) => (
          <div key={i} style={{ background: T.surface0, borderRadius: 4, padding: '7px 9px', border: `1px solid ${T.outlineSoft}` }}>
            <div style={{ fontFamily: T.font, fontSize: 9, color: T.textMuted, textTransform: 'uppercase', letterSpacing: '0.07em' }}>{s.label}</div>
            <div style={{ fontFamily: T.font, fontSize: 13, fontWeight: 700, color: T.text, marginTop: 2 }}>{s.val}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function LogTable({ entries }) {
  const scrollRef = useRef(null);
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [entries.length]);

  const rowColors = {
    switch:    { bg: 'rgba(59,130,246,0.06)', dot: T.blue,    badge: 'rgba(59,130,246,0.18)',  badgeText: '#93c5fd' },
    hold:      { bg: 'transparent',           dot: T.outline, badge: 'rgba(61,74,61,0.4)',     badgeText: T.textDim },
    blocked:   { bg: 'rgba(238,152,0,0.06)',  dot: T.amber,   badge: 'rgba(238,152,0,0.18)',   badgeText: T.amberBr },
    guardrail: { bg: 'rgba(239,68,68,0.06)',  dot: T.red,     badge: 'rgba(239,68,68,0.18)',   badgeText: T.redBr },
  };
  const typeLabel = { switch: 'SWITCH', hold: 'HOLD', blocked: 'BLOCKED', guardrail: 'GUARDRAIL' };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '52px 12px 156px 1fr 56px 70px', padding: '8px 16px', background: T.surface0, borderBottom: `1px solid ${T.outlineSoft}`, fontFamily: T.font, fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: T.textMuted }}>
        <span>Time</span><span></span><span>Decision</span><span>Reason</span><span style={{ textAlign: 'right' }}>Conf</span><span style={{ textAlign: 'center' }}>Type</span>
      </div>
      <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', maxHeight: 220 }}>
        {entries.length === 0 ? (
          <div style={{ padding: '40px 20px', textAlign: 'center', fontFamily: T.font, fontSize: 12, color: T.textMuted }}>Press Run Simulation to begin…</div>
        ) : entries.map((entry, i) => {
          const c = rowColors[entry.type] || rowColors.hold;
          const isLatest = i === entries.length - 1;
          return (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '52px 12px 156px 1fr 56px 70px', padding: '7px 16px', background: isLatest ? `${T.primary}10` : c.bg, borderBottom: `1px solid ${T.surface1}`, alignItems: 'center' }}>
              <span style={{ fontFamily: T.mono, fontSize: 10, fontWeight: 600, color: T.textDim }}>t={entry.t}m</span>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: c.dot, display: 'inline-block', boxShadow: isLatest ? `0 0 6px ${c.dot}` : 'none' }} />
              <span style={{ fontFamily: T.font, fontSize: 11, fontWeight: 600, color: T.text }}>
                {entry.from !== entry.to ? <><span style={{ color: H_INFO[entry.from]?.color || T.textDim }}>{entry.from}</span> → <span style={{ color: H_INFO[entry.to]?.color || T.textDim }}>{entry.to}</span></> : <span style={{ color: H_INFO[entry.to]?.color || T.textDim }}>{entry.to}</span>}
              </span>
              <span style={{ fontFamily: T.font, fontSize: 11, color: T.textDim, lineHeight: 1.4, paddingRight: 6 }}>{entry.plain}</span>
              <span style={{ fontFamily: T.mono, fontSize: 10, fontWeight: 600, color: entry.conf !== null ? T.text : T.textMuted, textAlign: 'right' }}>{entry.conf !== null ? entry.conf.toFixed(2) : '—'}</span>
              <span style={{ textAlign: 'center' }}>
                <span style={{ fontFamily: T.font, fontSize: 8, fontWeight: 700, padding: '2px 6px', borderRadius: 3, background: c.badge, color: c.badgeText, letterSpacing: '0.06em' }}>{typeLabel[entry.type]}</span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function Simulation() {
  const [presetId, setPresetId]       = useState('balanced');
  const [baselineH, setBaselineH]     = useState('FIFO');
  const [speed, setSpeed]             = useState(2);

  const [phase, setPhase]             = useState('idle');
  const [statusMsg, setStatusMsg]     = useState('');
  const [errorMsg, setErrorMsg]       = useState('');
  const [data, setData]               = useState(null);
  const [snapIdx, setSnapIdx]         = useState(0);

  const wsRef       = useRef(null);
  const intervalRef = useRef(null);

  const presetCfg = PRESETS.find((p) => p.id === presetId) || PRESETS[0];

  const dahsSnap = data && data.dahs[snapIdx]    || data?.dahs?.[data.dahs.length - 1]     || null;
  const baseSnap = data && data.baseline[snapIdx] || data?.baseline?.[data.baseline.length - 1] || null;
  const totalSnaps = data?.baseline?.length || 0;
  const simTime = dahsSnap?.time || baseSnap?.time || 0;

  const fullLog = useMemo(() => convertEvalLog(data?.evaluationLog), [data]);
  const revealedLog = useMemo(() => fullLog.filter((e) => e.t <= simTime), [fullLog, simTime]);
  const switchCount = revealedLog.filter((e) => e.type === 'switch').length;
  const latestEntry = revealedLog[revealedLog.length - 1];

  const baselineDisplayLabel = (() => {
    if (data?.presetFavoredHeuristic) return H_KEY_TO_LABEL[data.presetFavoredHeuristic] || baselineH;
    if (presetCfg.preset) return H_KEY_TO_LABEL[presetCfg.preset] || baselineH;
    return baselineH;
  })();

  function cleanup() {
    if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
    if (wsRef.current) {
      try { wsRef.current.close(); } catch {}
      wsRef.current = null;
    }
  }

  function startSim() {
    cleanup();
    setPhase('running');
    setStatusMsg('Connecting to backend…');
    setErrorMsg('');
    setData(null);
    setSnapIdx(0);

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${window.location.host}/ws/simulate`;
    let ws;
    try { ws = new WebSocket(url); }
    catch (e) { setPhase('error'); setErrorMsg(`Failed to open WebSocket: ${e.message}`); return; }
    wsRef.current = ws;

    ws.onopen = () => {
      setStatusMsg('Running real simulation (DAHS + baseline, 600 min)…');
      const config = { seed: 42, model: 'xgb', baseCode: baselineH, params: {} };
      if (presetCfg.preset) config.preset = presetCfg.preset;
      ws.send(JSON.stringify(config));
    };

    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === 'status') setStatusMsg(msg.msg || statusMsg);
      else if (msg.type === 'snapshots') { setData(msg); setPhase('playing'); setSnapIdx(0); }
      else if (msg.type === 'error') { setPhase('error'); setErrorMsg(msg.msg || 'Backend error'); }
    };
    ws.onerror = () => { setPhase('error'); setErrorMsg('WebSocket connection failed. Is the backend running on :8000?'); };
    ws.onclose = () => { wsRef.current = null; };
  }

  useEffect(() => {
    if (phase !== 'playing' || !data) return;
    if (intervalRef.current) clearInterval(intervalRef.current);
    const msPerSnap = Math.max(8, 60 / speed);
    intervalRef.current = setInterval(() => {
      setSnapIdx((i) => {
        const next = i + 1;
        if (next >= totalSnaps - 1) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
          setPhase('done');
          return totalSnaps - 1;
        }
        return next;
      });
    }, msPerSnap);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [phase, data, speed, totalSnaps]);

  function reset() {
    cleanup();
    setPhase('idle');
    setData(null);
    setSnapIdx(0);
    setStatusMsg('');
    setErrorMsg('');
  }

  useEffect(() => () => cleanup(), []);

  const running = phase === 'running' || phase === 'playing';
  const simDone = phase === 'done';

  const selectStyle = {
    padding: '7px 14px', borderRadius: 4, border: `1px solid ${T.outlineSoft}`,
    background: T.surface1, color: T.text, fontFamily: T.font, fontSize: 12, fontWeight: 600,
    cursor: running ? 'not-allowed' : 'pointer',
  };

  return (
    <div style={{ background: T.bg, minHeight: '100vh', paddingTop: 80, display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden', fontFamily: T.font, color: T.text }}>

      <div style={{ padding: '14px 24px 12px', background: T.surface1, borderBottom: `1px solid ${T.outlineSoft}`, display: 'flex', alignItems: 'center', gap: 16, flexShrink: 0 }}>
        <div style={{ width: 8, height: 8, borderRadius: '50%', background: running ? T.primary : (phase === 'error' ? T.red : T.outline), boxShadow: running ? `0 0 10px ${T.primary}` : 'none', animation: running ? 'pulse 1.2s infinite' : 'none' }} />
        <h1 style={{ margin: 0, fontFamily: T.font, fontSize: 22, fontWeight: 600, color: T.text, letterSpacing: '-0.01em' }}>DAHS 2.0 Simulation Comparison Dashboard</h1>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <select value={presetId} onChange={(e) => { setPresetId(e.target.value); reset(); }} disabled={running} style={selectStyle}>
            {PRESETS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
          {!presetCfg.preset && (
            <select value={baselineH} onChange={(e) => { setBaselineH(e.target.value); reset(); }} disabled={running} style={selectStyle}>
              {Object.keys(H_INFO).map((h) => <option key={h}>{h}</option>)}
            </select>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, background: T.surface0, padding: 3, borderRadius: 4, border: `1px solid ${T.outlineSoft}` }}>
            {[1, 2, 4, 8].map((s) => (
              <button key={s} onClick={() => setSpeed(s)} style={{ padding: '4px 10px', borderRadius: 3, border: 'none', background: speed === s ? T.primary : 'transparent', color: speed === s ? '#003915' : T.textDim, fontFamily: T.font, fontSize: 11, fontWeight: 700, cursor: 'pointer' }}>{s}×</button>
            ))}
          </div>
          <button onClick={running ? reset : startSim} style={{ padding: '8px 22px', borderRadius: 4, border: 'none', background: running ? T.red : T.primary, color: running ? '#fff' : '#003915', fontFamily: T.font, fontWeight: 700, fontSize: 13, cursor: 'pointer', boxShadow: running ? `0 0 18px ${T.red}55` : `0 0 18px ${T.primary}55`, letterSpacing: '0.02em' }}>
            {running ? '■ STOP' : simDone ? '↺ RE-RUN' : '▶ RUN'}
          </button>
        </div>
      </div>

      {(phase === 'running' || phase === 'error') && (
        <div style={{ padding: '8px 24px', background: phase === 'error' ? `${T.red}12` : `${T.blue}10`, borderBottom: `1px solid ${T.outlineSoft}`, display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
          {phase === 'running' && (
            <>
              <div style={{ width: 12, height: 12, borderRadius: '50%', border: `2px solid ${T.primary}`, borderTopColor: 'transparent', animation: 'spin 0.8s linear infinite' }} />
              <span style={{ fontFamily: T.font, fontSize: 12, color: T.text }}>{statusMsg}</span>
            </>
          )}
          {phase === 'error' && (
            <span style={{ fontFamily: T.font, fontSize: 12, color: T.redBr }}>⚠ {errorMsg}</span>
          )}
        </div>
      )}

      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 320px', overflow: 'hidden' }}>

        <div style={{ display: 'flex', flexDirection: 'column', overflow: 'auto', padding: 16, gap: 14, borderRight: `1px solid ${T.outlineSoft}` }}>
          <ArmCard
            title="DAHS"
            tag={`Adaptive Hybrid Solver (${latestEntry?.to || 'FIFO'})`}
            accent={T.primary}
            snap={dahsSnap}
            otherSnap={baseSnap}
            isDahs
          />
          <ArmCard
            title="Baseline"
            tag={`Static ${baselineDisplayLabel} dispatch`}
            accent={T.amberBr}
            snap={baseSnap}
            otherSnap={dahsSnap}
            isDahs={false}
          />

          <HeuristicTimeline log={fullLog} currentTime={Math.round(simTime)} simDone={simDone} />

          <div style={{ flexShrink: 0, background: T.surface1, borderRadius: 6, border: `1px solid ${T.outlineSoft}`, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <div style={{ padding: '9px 16px', background: T.surface0, borderBottom: `1px solid ${T.outlineSoft}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontFamily: T.font, fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', color: T.textDim }}>DAHS Evaluation Log — {revealedLog.length}/{fullLog.length}</span>
              <div style={{ display: 'flex', gap: 12 }}>
                {[{ c: T.blue, l: 'Switch' }, { c: T.amber, l: 'Blocked' }, { c: T.red, l: 'Guardrail' }, { c: T.outline, l: 'Hold' }].map((b) => (
                  <span key={b.l} style={{ display: 'flex', alignItems: 'center', gap: 5, fontFamily: T.font, fontSize: 10, color: T.textMuted }}>
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: b.c }} />{b.l}
                  </span>
                ))}
              </div>
            </div>
            <LogTable entries={revealedLog} />
          </div>
        </div>

        <div style={{ background: T.surface1, padding: 16, display: 'flex', flexDirection: 'column', gap: 14, overflowY: 'auto', flexShrink: 0 }}>
          <div style={{ background: T.surface0, borderRadius: 6, border: `1px solid ${T.outlineSoft}`, padding: '10px 12px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <div>
              <div style={{ fontFamily: T.font, fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: T.textMuted, marginBottom: 2 }}>Sim Time</div>
              <div style={{ fontFamily: T.mono, fontSize: 14, fontWeight: 700, color: T.text }}>{data ? `${Math.round(simTime)} / 600m` : '—'}</div>
            </div>
            <div>
              <div style={{ fontFamily: T.font, fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: T.textMuted, marginBottom: 2 }}>Switches</div>
              <div style={{ fontFamily: T.mono, fontSize: 14, fontWeight: 700, color: T.primaryBr }}>{switchCount}</div>
            </div>
          </div>

          <ActiveHeuristicPanel entry={latestEntry} switchCount={switchCount} />

          <div style={{ background: T.surface2, borderRadius: 6, border: `1px solid ${T.outlineSoft}`, padding: '14px 14px' }}>
            <div style={{ fontFamily: T.font, fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', color: T.textDim, marginBottom: 14 }}>DAHS vs {baselineDisplayLabel}</div>
            <ComparisonPanel dahsSnap={dahsSnap} baseSnap={baseSnap} baselineLabel={baselineDisplayLabel} />
          </div>

          <div style={{ background: T.surface2, borderRadius: 6, border: `1px solid ${T.outlineSoft}`, padding: '12px 14px' }}>
            <div style={{ fontFamily: T.font, fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: T.textMuted, marginBottom: 6 }}>Scenario</div>
            <div style={{ fontFamily: T.font, fontSize: 13, fontWeight: 700, color: T.text, marginBottom: 4 }}>{presetCfg.label}</div>
            <div style={{ fontFamily: T.font, fontSize: 11, color: T.textDim, lineHeight: 1.55 }}>{presetCfg.desc}</div>
            {data?.presetWhyItFavors && (
              <div style={{ marginTop: 9, paddingTop: 8, borderTop: `1px solid ${T.outlineSoft}`, fontFamily: T.font, fontSize: 11, color: T.textMuted, lineHeight: 1.55, fontStyle: 'italic' }}>
                {data.presetWhyItFavors}
              </div>
            )}
          </div>

          {data?.switchingSummary && (
            <div style={{ background: T.surface2, borderRadius: 6, border: `1px solid ${T.outlineSoft}`, padding: '12px 14px' }}>
              <div style={{ fontFamily: T.font, fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: T.textMuted, marginBottom: 8 }}>DAHS Summary</div>
              {[
                { label: 'Total evaluations', val: data.switchingSummary.totalEvaluations },
                { label: 'Switches',          val: data.switchingSummary.switchCount },
                { label: 'Hysteresis blocks', val: data.switchingSummary.hysteresisBlocked },
                { label: 'Guardrail fires',   val: data.switchingSummary.guardrailActivations },
              ].map((r, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontFamily: T.font, fontSize: 11, color: T.textDim, padding: '4px 0' }}>
                  <span>{r.label}</span>
                  <span style={{ fontFamily: T.mono, color: T.text, fontWeight: 700 }}>{r.val ?? '—'}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
      `}</style>
    </div>
  );
}
