import React, { useEffect, useRef, useState } from 'react';
import { Brain } from 'lucide-react';

const HEURISTICS = [
  { code: 'fifo',           label: 'FIFO',         color: '#64748B' },
  { code: 'priority_edd',   label: 'Priority-EDD', color: '#0EA5E9' },
  { code: 'critical_ratio', label: 'Critical-Ratio', color: '#F59E0B' },
  { code: 'atc',            label: 'ATC',          color: '#DC2626' },
  { code: 'wspt',           label: 'WSPT',         color: '#16A34A' },
  { code: 'slack',          label: 'Slack',        color: '#A855F7' },
];

// Conceptual time-series of warehouse states. Each entry: chosen heuristic + reason + bars.
const TICKS = [
  { h: 'fifo',           reason: 'Light load (12 orders) → FIFO is enough',          bars: [0.18, 0.30, 0.20] },
  { h: 'priority_edd',   reason: 'Express ramp-up → favor near-deadline jobs',       bars: [0.45, 0.55, 0.62] },
  { h: 'wspt',           reason: 'Many short jobs queued → WSPT minimizes wait',     bars: [0.62, 0.70, 0.40] },
  { h: 'atc',            reason: 'High utilization + tight deadlines → ATC',         bars: [0.85, 0.92, 0.78] },
  { h: 'critical_ratio', reason: 'Station breakdown → re-rank by remaining slack',   bars: [0.55, 0.96, 0.65] },
  { h: 'slack',          reason: 'Recovery phase → balance load via slack',          bars: [0.40, 0.62, 0.30] },
];

const TICK_MS = 1700;

function colorOf(code) {
  return HEURISTICS.find(h => h.code === code)?.color || '#64748B';
}
function labelOf(code) {
  return HEURISTICS.find(h => h.code === code)?.label || code;
}

export default function MetaSelectorAnimation() {
  const [idx, setIdx] = useState(0);
  const [paused, setPaused] = useState(false);
  const timerRef = useRef(null);

  useEffect(() => {
    if (paused) return;
    timerRef.current = setInterval(() => setIdx(i => (i + 1) % TICKS.length), TICK_MS);
    return () => clearInterval(timerRef.current);
  }, [paused]);

  const tick = TICKS[idx];
  const chosen = tick.h;

  // Geometry for the 6 chips on a ring
  const cx = 320, cy = 200, r = 140;
  const chipPositions = HEURISTICS.map((_, i) => {
    const angle = (i / HEURISTICS.length) * 2 * Math.PI - Math.PI / 2;
    return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle), angle };
  });

  return (
    <div
      className="relative w-full max-w-3xl mx-auto bg-white rounded-3xl border border-border/60 shadow-soft p-6"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      <div className="flex items-center justify-between mb-3">
        <span className="font-body text-[11px] font-bold uppercase tracking-widest text-muted-foreground">
          Conceptual illustration
        </span>
        <span className="text-[11px] font-body text-muted-foreground">
          Hover to pause
        </span>
      </div>

      {/* SVG meta-selector */}
      <svg viewBox="0 0 640 400" className="w-full h-auto">
        {/* Connection arcs from brain to chips */}
        {chipPositions.map((p, i) => {
          const isChosen = HEURISTICS[i].code === chosen;
          return (
            <line
              key={i}
              x1={cx} y1={cy} x2={p.x} y2={p.y}
              stroke={isChosen ? colorOf(chosen) : '#E2E8F0'}
              strokeWidth={isChosen ? 3 : 1}
              strokeDasharray={isChosen ? '0' : '4 4'}
              opacity={isChosen ? 1 : 0.5}
              style={{ transition: 'stroke 600ms ease, stroke-width 600ms ease, opacity 600ms ease' }}
            />
          );
        })}

        {/* Heuristic chips */}
        {HEURISTICS.map((h, i) => {
          const p = chipPositions[i];
          const isChosen = h.code === chosen;
          return (
            <g key={h.code} style={{ transition: 'transform 600ms ease' }}>
              <circle
                cx={p.x} cy={p.y}
                r={isChosen ? 32 : 24}
                fill={isChosen ? h.color : 'white'}
                stroke={h.color}
                strokeWidth={2.5}
                style={{ transition: 'all 600ms ease' }}
              />
              <text
                x={p.x} y={p.y + 4}
                textAnchor="middle"
                fontSize={isChosen ? 12 : 10}
                fontWeight={700}
                fill={isChosen ? 'white' : h.color}
                fontFamily="ui-sans-serif, system-ui"
                style={{ transition: 'all 600ms ease' }}
              >
                {h.label}
              </text>
            </g>
          );
        })}

        {/* Brain core */}
        <circle cx={cx} cy={cy} r={56} fill={colorOf(chosen)} opacity={0.12}>
          <animate attributeName="r" values="56;62;56" dur="1.5s" repeatCount="indefinite" />
        </circle>
        <circle cx={cx} cy={cy} r={48} fill="white" stroke={colorOf(chosen)} strokeWidth={2.5}
                style={{ transition: 'stroke 600ms ease' }} />
        <foreignObject x={cx - 24} y={cy - 24} width={48} height={48}>
          <div className="w-full h-full flex items-center justify-center"
               style={{ color: colorOf(chosen), transition: 'color 600ms ease' }}>
            <Brain size={28} strokeWidth={2.2} />
          </div>
        </foreignObject>
        <text x={cx} y={cy + 80} textAnchor="middle"
              fontSize={11} fontWeight={700} fill="#0F172A"
              fontFamily="ui-sans-serif, system-ui">
          DAHS Selector
        </text>
      </svg>

      {/* State bars */}
      <div className="grid grid-cols-3 gap-3 mt-4">
        {[
          { name: 'Orders',       v: tick.bars[0] },
          { name: 'Utilization',  v: tick.bars[1] },
          { name: 'Time pressure',v: tick.bars[2] },
        ].map((b, i) => (
          <div key={i} className="bg-slate-50 rounded-xl p-3 border border-border/40">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[10px] font-body font-bold uppercase tracking-wider text-slate-500">
                {b.name}
              </span>
              <span className="text-[10px] font-mono text-slate-700">{Math.round(b.v * 100)}%</span>
            </div>
            <div className="h-2 rounded-full bg-slate-200 overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${b.v * 100}%`,
                  background: colorOf(chosen),
                  transition: 'all 800ms ease',
                }}
              />
            </div>
          </div>
        ))}
      </div>

      {/* Reason caption */}
      <div className="mt-4 px-4 py-3 rounded-xl border-2"
           style={{ borderColor: colorOf(chosen), background: colorOf(chosen) + '0D' }}>
        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider"
                style={{ background: colorOf(chosen), color: 'white' }}>
            {labelOf(chosen)}
          </span>
          <span className="font-body text-sm text-foreground">{tick.reason}</span>
        </div>
      </div>

      {/* Tick dots */}
      <div className="flex justify-center gap-2 mt-4">
        {TICKS.map((_, i) => (
          <button
            key={i}
            onClick={() => setIdx(i)}
            className="w-2 h-2 rounded-full transition-all"
            style={{
              background: i === idx ? colorOf(chosen) : '#CBD5E1',
              transform: i === idx ? 'scale(1.4)' : 'scale(1)',
            }}
            aria-label={`Go to step ${i + 1}`}
          />
        ))}
      </div>
    </div>
  );
}
