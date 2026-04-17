import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Play, Pause, RotateCcw, BarChart2, ChevronDown, Shield, Zap, Clock, Brain } from 'lucide-react';

const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/simulate`;
const SNAP_INTERVAL = 2.0;
const SIM_SPEED = 4;
const JOB_COLORS = { A: '#60a5fa', B: '#4ade80', C: '#fb923c', D: '#fbbf24', E: '#c084fc' };


/* ── Canvas helper ──────────────────────────────────────────── */
function rr(ctx, x, y, w, h, r) {
  if (w <= 0 || h <= 0) return;
  r = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

/* ── Side-by-side warehouse canvas (ported from DAHS_1) ─────── */
function WarehouseCanvas({ snapshot, label, accentColor }) {
  const canvasRef = useRef(null);
  const animRef = useRef(null);
  const snapRef = useRef(snapshot);

  useEffect(() => { snapRef.current = snapshot; }, [snapshot]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const W = canvas.offsetWidth, H = canvas.offsetHeight;
      canvas.width = W * dpr; canvas.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    const ZONE_NR = [
      { rx: 0.010, ry: 0.030, rw: 0.205, rh: 0.44 },
      { rx: 0.235, ry: 0.030, rw: 0.210, rh: 0.44 },
      { rx: 0.465, ry: 0.030, rw: 0.240, rh: 0.44 },
      { rx: 0.725, ry: 0.030, rw: 0.265, rh: 0.44 },
      { rx: 0.725, ry: 0.535, rw: 0.265, rh: 0.43 },
      { rx: 0.465, ry: 0.535, rw: 0.240, rh: 0.43 },
      { rx: 0.235, ry: 0.535, rw: 0.210, rh: 0.43 },
      { rx: 0.010, ry: 0.535, rw: 0.205, rh: 0.43 },
    ];
    const ZONE_META = [
      { name: 'INBOUND DOCK', short: 'RECV', stations: 3, bg: '#EFF6FF', bd: '#93C5FD', hdr: '#2563EB', cols: 3 },
      { name: 'SORTING',      short: 'SORT', stations: 4, bg: '#F0FDF4', bd: '#86EFAC', hdr: '#16A34A', cols: 2 },
      { name: 'PICKING — A',  short: 'PKG-A',stations: 6, bg: '#FFFBEB', bd: '#FCD34D', hdr: '#D97706', cols: 3 },
      { name: 'PICKING — B',  short: 'PKG-B',stations: 8, bg: '#FFF7ED', bd: '#FDBA74', hdr: '#EA580C', cols: 4 },
      { name: 'VALUE-ADD',    short: 'VAL',  stations: 5, bg: '#FDF4FF', bd: '#E879F9', hdr: '#A21CAF', cols: 3 },
      { name: 'QUALITY CTRL', short: 'QC',   stations: 4, bg: '#ECFDF5', bd: '#6EE7B7', hdr: '#059669', cols: 2 },
      { name: 'PACKING',      short: 'PACK', stations: 3, bg: '#F5F3FF', bd: '#C4B5FD', hdr: '#7C3AED', cols: 3 },
      { name: 'OUTBOUND DOCK',short: 'SHIP', stations: 4, bg: '#F0F9FF', bd: '#7DD3FC', hdr: '#0284C7', cols: 2 },
    ];
    const BELT_DEFS = [
      [0,1,0.50,1,0,0.50],[1,1,0.50,2,0,0.50],[2,1,0.50,3,0,0.50],
      [3,0.50,1,4,0.50,0],[4,0,0.50,5,1,0.50],[5,0,0.50,6,1,0.50],[6,0,0.50,7,1,0.50],
    ];

    let t0 = performance.now();

    const draw = (now) => {
      const W = canvas.offsetWidth, H = canvas.offsetHeight;
      const snap = snapRef.current;
      const t = (now - t0) / 1000;
      ctx.clearRect(0, 0, W, H);

      // Floor
      ctx.fillStyle = '#EEF2F7';
      ctx.fillRect(0, 0, W, H);
      const tSz = Math.max(20, Math.round(W / 22));
      ctx.strokeStyle = 'rgba(148,163,184,0.18)'; ctx.lineWidth = 0.5;
      for (let x = 0; x < W; x += tSz) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
      for (let y = 0; y < H; y += tSz) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }

      const zr = ZONE_NR.map(n => ({ x: n.rx * W, y: n.ry * H, w: n.rw * W, h: n.rh * H }));

      // Belts
      BELT_DEFS.forEach(([fi, fx, fy, ti, tx, ty]) => {
        const fz = zr[fi], tz = zr[ti];
        const x1 = fz.x + fx * fz.w, y1 = fz.y + fy * fz.h;
        const x2 = tz.x + tx * tz.w, y2 = tz.y + ty * tz.h;
        const len = Math.hypot(x2 - x1, y2 - y1), ang = Math.atan2(y2 - y1, x2 - x1);
        ctx.save(); ctx.translate(x1, y1); ctx.rotate(ang);
        ctx.fillStyle = 'rgba(0,0,0,0.08)'; ctx.fillRect(-1, -7, len + 2, 14);
        ctx.fillStyle = '#94A3B8'; ctx.fillRect(0, -5, len, 10);
        ctx.fillStyle = '#64748B';
        const ribSpacing = 14, ribOffset = (t * 24) % ribSpacing;
        for (let sx = -ribOffset; sx < len + ribSpacing; sx += ribSpacing) ctx.fillRect(sx, -5, 2.5, 10);
        ctx.fillStyle = 'rgba(248,250,252,0.75)';
        for (let ax = 22; ax < len - 10; ax += 40) {
          ctx.beginPath(); ctx.moveTo(ax, 0); ctx.lineTo(ax - 7, -3.5); ctx.lineTo(ax - 7, 3.5); ctx.closePath(); ctx.fill();
        }
        ctx.restore();
      });

      const byZone = Array(8).fill(null).map(() => ({ proc: [], wait: [] }));
      if (snap?.activeJobs) {
        snap.activeJobs.slice(0, 200).forEach(j => {
          if (j.zoneId >= 0 && j.zoneId < 8) {
            if (j.status === 'processing') byZone[j.zoneId].proc.push(j);
            else byZone[j.zoneId].wait.push(j);
          }
        });
      }

      zr.forEach((z, i) => {
        const meta = ZONE_META[i];
        const qLen = snap?.zoneQueueLengths?.[i] || 0;
        const active = snap?.zoneActiveCounts?.[i] || 0;
        const load = active / meta.stations;
        const procJobs = byZone[i].proc, waitJobs = byZone[i].wait;

        ctx.shadowColor = 'rgba(30,58,138,0.10)'; ctx.shadowBlur = 8; ctx.shadowOffsetY = 3;
        rr(ctx, z.x, z.y, z.w, z.h, 7); ctx.fillStyle = meta.bg; ctx.fill();
        ctx.shadowBlur = 0; ctx.shadowOffsetY = 0;
        rr(ctx, z.x, z.y, z.w, z.h, 7);
        ctx.strokeStyle = load > 0.5 ? meta.hdr : meta.bd; ctx.lineWidth = load > 0.5 ? 2.5 : 1.5; ctx.stroke();

        const hr = 7;
        ctx.beginPath();
        ctx.moveTo(z.x + hr, z.y); ctx.lineTo(z.x + z.w - hr, z.y);
        ctx.quadraticCurveTo(z.x + z.w, z.y, z.x + z.w, z.y + hr);
        ctx.lineTo(z.x + z.w, z.y + 22); ctx.lineTo(z.x, z.y + 22); ctx.lineTo(z.x, z.y + hr);
        ctx.quadraticCurveTo(z.x, z.y, z.x + hr, z.y); ctx.closePath();
        ctx.fillStyle = meta.hdr; ctx.globalAlpha = 0.88; ctx.fill(); ctx.globalAlpha = 1;

        ctx.fillStyle = '#F0F9FF';
        ctx.font = `bold ${Math.min(8.5, z.w / 8)}px system-ui,sans-serif`;
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(meta.name, z.x + z.w / 2, z.y + 11);

        const dotCol = load > 0.7 ? '#EF4444' : load > 0.3 ? '#F59E0B' : '#10B981';
        ctx.beginPath(); ctx.arc(z.x + z.w - 9, z.y + 11, 3.5, 0, Math.PI * 2);
        ctx.fillStyle = dotCol; ctx.fill();

        const stCount = meta.stations, stCols = meta.cols, stRows = Math.ceil(stCount / stCols);
        const padX = 6, padY = 6;
        const avW = z.w - padX * 2, avH = z.h - 26 - padY * 2 - (qLen > 0 ? 22 : 4);
        const stW = Math.max(12, (avW - (stCols - 1) * 4) / stCols), stH = Math.max(10, (avH - (stRows - 1) * 4) / stRows);
        const gridW = stCols * stW + (stCols - 1) * 4, gridH = stRows * stH + (stRows - 1) * 4;
        const stStartX = z.x + (z.w - gridW) / 2, stStartY = z.y + 26 + (avH - gridH) / 2;

        for (let s = 0; s < stCount; s++) {
          const col = s % stCols, row = Math.floor(s / stCols);
          const sx = stStartX + col * (stW + 4), sy = stStartY + row * (stH + 4);
          const occupied = s < procJobs.length;
          rr(ctx, sx, sy, stW, stH, 3); ctx.fillStyle = occupied ? `${meta.hdr}28` : '#E2E8F0'; ctx.fill();
          rr(ctx, sx, sy, stW, stH, 3); ctx.strokeStyle = occupied ? meta.hdr : '#CBD5E1'; ctx.lineWidth = occupied ? 1.5 : 1; ctx.stroke();
          if (occupied && procJobs[s]) {
            const pad = 3; rr(ctx, sx + pad, sy + pad, stW - pad * 2, stH - pad * 2, 2);
            ctx.fillStyle = procJobs[s].color; ctx.fill();
          }
        }

        if (qLen > 0 || waitJobs.length > 0) {
          const qy = z.y + z.h - 22;
          ctx.fillStyle = 'rgba(15,23,42,0.05)'; ctx.fillRect(z.x + 2, qy, z.w - 4, 18);
          const maxDots = Math.min(waitJobs.length, Math.floor((z.w - 28) / 9));
          for (let w = 0; w < maxDots; w++) {
            const wx = z.x + 4 + w * 9; rr(ctx, wx, qy + 4, 7, 10, 1.5);
            ctx.fillStyle = waitJobs[w].color; ctx.globalAlpha = 0.85; ctx.fill(); ctx.globalAlpha = 1;
          }
          if (waitJobs.length > maxDots) {
            ctx.fillStyle = '#94A3B8'; ctx.font = '7px system-ui,sans-serif';
            ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
            ctx.fillText(`+${waitJobs.length - maxDots}`, z.x + 4 + maxDots * 9, qy + 9);
          }
          ctx.fillStyle = qLen > 10 ? '#DC2626' : '#374151';
          ctx.font = `bold ${Math.min(8, z.w / 9)}px system-ui,sans-serif`;
          ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
          ctx.fillText(`Q:${qLen}`, z.x + z.w - 3, qy + 9);
        }
      });

      if (snap) {
        ctx.fillStyle = 'rgba(15,23,42,0.35)'; ctx.font = '9px system-ui,sans-serif';
        ctx.textAlign = 'left'; ctx.textBaseline = 'top';
        ctx.fillText(`t = ${snap.time.toFixed(1)} min`, 8, 5);
      }
      ctx.fillStyle = accentColor; ctx.font = 'bold 9px system-ui,sans-serif';
      ctx.textAlign = 'right'; ctx.textBaseline = 'top';
      ctx.fillText(label, canvas.offsetWidth - 8, 5);

      animRef.current = requestAnimationFrame(draw);
    };

    animRef.current = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(animRef.current); ro.disconnect(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accentColor, label]);

  return <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block' }} />;
}

/* ── Metric bar ─────────────────────────────────────────────── */
function MetricBar({ label, baseVal, dahsVal, unit = '', lowerIsBetter = true, baseLabel = 'Baseline' }) {
  const max = Math.max(baseVal, dahsVal) * 1.2 || 1;
  const baseW = Math.min((baseVal / max) * 100, 100);
  const dahsW = Math.min((dahsVal / max) * 100, 100);
  const wins = lowerIsBetter ? dahsVal < baseVal : dahsVal > baseVal;
  const pct = baseVal > 0 ? Math.abs((baseVal - dahsVal) / baseVal * 100).toFixed(1) : '—';
  const dp = unit === '%' || unit.includes('hr') ? 1 : 0;

  return (
    <div className="mb-4">
      <div className="flex justify-between items-baseline mb-1.5">
        <span className="font-body text-sm font-semibold text-foreground/75">{label}</span>
        {wins && baseVal > 0 && (
          <span className="font-body text-xs font-bold text-primary bg-primary/10 px-2 py-0.5 rounded-full">
            {lowerIsBetter ? '-' : '+'}{pct}%
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 mb-1">
        <span className="font-body text-[10px] text-muted-foreground w-14 text-right shrink-0">{baseLabel}</span>
        <div className="flex-1 h-4 bg-muted rounded-full overflow-hidden">
          <div className="h-full rounded-full transition-all duration-700" style={{ width: `${baseW}%`, background: '#64748B' }} />
        </div>
        <span className="font-body text-[10px] font-mono text-muted-foreground w-16 shrink-0">
          {typeof baseVal === 'number' ? baseVal.toFixed(dp) : '—'}{unit}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <span className="font-body text-[10px] text-primary font-bold w-14 text-right shrink-0">DAHS</span>
        <div className="flex-1 h-4 bg-muted rounded-full overflow-hidden">
          <div className="h-full rounded-full transition-all duration-700" style={{ width: `${dahsW}%`, background: '#1E3A8A' }} />
        </div>
        <span className="font-body text-[10px] font-mono font-bold text-primary w-16 shrink-0">
          {typeof dahsVal === 'number' ? dahsVal.toFixed(dp) : '—'}{unit}
        </span>
      </div>
    </div>
  );
}

/* ── Evaluation log entry ────────────────────────────────────── */
function EvalEntry({ entry }) {
  const [open, setOpen] = useState(false);
  const reasonColors = {
    ml_decision: 'bg-blue-100 text-blue-800',
    hysteresis_blocked: 'bg-yellow-100 text-yellow-800',
    guardrail_trivial: 'bg-gray-100 text-gray-800',
    guardrail_overload: 'bg-orange-100 text-orange-800',
    guardrail_ood: 'bg-red-100 text-red-800',
  };
  const rColor = reasonColors[entry.reason] || 'bg-slate-100 text-slate-700';

  const heuristic_colors_map = {
    fifo: '#94A3B8', priority_edd: '#64748B', critical_ratio: '#6B7280',
    atc: '#3B82F6', wspt: '#2563EB', slack: '#78716C',
  };

  return (
    <div className="eval-entry bg-white rounded-xl border border-border/40 overflow-hidden">
      <button
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-slate-50 transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <span className="font-mono text-xs text-muted-foreground w-12 shrink-0">t={entry.time}</span>
        <span
          className="w-2.5 h-2.5 rounded-full shrink-0"
          style={{ background: heuristic_colors_map[entry.heuristic] || '#94A3B8' }}
        />
        <span className="font-body text-xs font-bold text-foreground flex-1">{entry.heuristic}</span>
        {entry.switched && <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-primary/10 text-primary">SWITCH</span>}
        <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full ${rColor}`}>{entry.reason}</span>
        <span className="font-mono text-[10px] text-muted-foreground">{(entry.confidence * 100).toFixed(0)}%</span>
        <ChevronDown size={12} className={`text-muted-foreground transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="px-4 py-3 border-t border-border/30 bg-slate-50/70 space-y-3">
          {entry.plainEnglish && (
            <div className="p-3 rounded-lg bg-primary/5 border border-primary/15">
              <p className="font-body text-xs text-primary/90 leading-relaxed">
                <strong>Plain English:</strong> {entry.plainEnglish}
              </p>
            </div>
          )}
          {entry.topFeatures?.length > 0 && (
            <div>
              <p className="font-body text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-2">Top Features (attribution)</p>
              <div className="space-y-1.5">
                {entry.topFeatures.map((f, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <span className="font-mono text-[10px] text-foreground w-36 shrink-0">{f.name}</span>
                    <div className="flex-1 h-2 bg-slate-200 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full bg-primary"
                        style={{ width: `${Math.min(f.importance * 500, 100)}%` }}
                      />
                    </div>
                    <span className="font-mono text-[10px] text-muted-foreground">{f.value?.toFixed(3)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {entry.probabilities && Object.keys(entry.probabilities).length > 0 && (
            <div>
              <p className="font-body text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-2">Class Probabilities</p>
              <div className="grid grid-cols-3 gap-1.5">
                {Object.entries(entry.probabilities).map(([h, p]) => (
                  <div key={h} className={`rounded px-2 py-1 text-center ${h === entry.heuristic ? 'bg-primary/10 border border-primary/30' : 'bg-slate-100'}`}>
                    <p className="font-mono text-[9px] font-bold text-foreground">{h}</p>
                    <p className="font-mono text-[10px] text-primary">{(p * 100).toFixed(0)}%</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const BASE_STRATEGIES = [
  { code: 'FIFO',           name: 'FIFO (First In, First Out)' },
  { code: 'EDD',            name: 'Priority-EDD' },
  { code: 'Critical-Ratio', name: 'Critical Ratio' },
  { code: 'ATC',            name: 'Apparent Tardiness Cost' },
  { code: 'WSPT',           name: 'Weighted Shortest Proc Time' },
  { code: 'Slack',          name: 'Minimum Slack Time' },
];

/* ════════════════════════════════════════════════════════════════
   SIMULATION PAGE
════════════════════════════════════════════════════════════════ */
export default function Simulation() {
  const [seed,          setSeed]          = useState(42);
  const [baseCode,      setBaseCode]      = useState('FIFO');
  const [selectedModel, setSelectedModel] = useState('xgb');
  const [presets,        setPresets]        = useState([]);
  const [selectedPreset, setSelectedPreset] = useState('none');
  const [baseArrivalRate, setBaseArrivalRate] = useState(2.5);
  const [breakdownProb,   setBreakdownProb]   = useState(0.003);
  const [batchArrivalSize,setBatchArrivalSize] = useState(30);
  const [lunchPenalty,    setLunchPenalty]    = useState(0.3);

  const [wsStatus,    setWsStatus]    = useState('idle');
  const [wsError,     setWsError]     = useState('');
  const [running,     setRunning]     = useState(false);
  const [simTime,     setSimTime]     = useState(0);
  const [fifoSnap,    setFifoSnap]    = useState(null);
  const [hybridSnap,  setHybridSnap]  = useState(null);
  const [finished,    setFinished]    = useState(false);
  const [fifoFinal,   setFifoFinal]   = useState(null);
  const [hybridFinal, setHybridFinal] = useState(null);
  const [evalLog,     setEvalLog]     = useState([]);
  const [switchingSummary, setSwitchingSummary] = useState(null);
  const [presetMeta,  setPresetMeta]  = useState(null);
  const [showLog,     setShowLog]     = useState(false);

  const baselineSnapsRef = useRef([]);
  const dahsSnapsRef     = useRef([]);
  const simTimeRef       = useRef(0);
  const tickRef          = useRef(null);
  const wsRef            = useRef(null);

  useEffect(() => {
    fetch('/api/presets')
      .then(r => r.ok ? r.json() : [])
      .then(data => setPresets(data))
      .catch(() => setPresets([]));
  }, []);

  const enrichSnap = (snap) => {
    if (!snap) return snap;
    return {
      ...snap,
      activeJobs: (snap.activeJobs || []).map(j => ({
        ...j, color: j.color || JOB_COLORS[j.type] || '#94A3B8',
      })),
    };
  };

  const reset = useCallback(() => {
    cancelAnimationFrame(tickRef.current);
    if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
    baselineSnapsRef.current = [];
    dahsSnapsRef.current     = [];
    simTimeRef.current       = 0;
    setSimTime(0); setRunning(false); setFinished(false);
    setFifoSnap(null); setHybridSnap(null);
    setFifoFinal(null); setHybridFinal(null);
    setWsStatus('idle'); setWsError('');
    setEvalLog([]); setSwitchingSummary(null); setPresetMeta(null);
  }, []);

  useEffect(() => {
    if (!running) { cancelAnimationFrame(tickRef.current); return; }
    const total = baselineSnapsRef.current.length;
    if (!total) return;
    let lastReal = performance.now();
    const tick = (now) => {
      const dtSec = Math.min((now - lastReal) / 1000, 0.05);
      lastReal = now;
      const nextT = Math.min(simTimeRef.current + dtSec * SIM_SPEED * 60, 600);
      simTimeRef.current = nextT;
      const idx = Math.min(Math.floor(nextT / SNAP_INTERVAL), total - 1);
      setFifoSnap(enrichSnap(baselineSnapsRef.current[idx]));
      setHybridSnap(enrichSnap(dahsSnapsRef.current[idx]));
      setSimTime(nextT);
      if (nextT >= 600) {
        setRunning(false); setFinished(true);
        setFifoFinal(baselineSnapsRef.current[total - 1]?.metrics || null);
        setHybridFinal(dahsSnapsRef.current[total - 1]?.metrics || null);
        return;
      }
      tickRef.current = requestAnimationFrame(tick);
    };
    tickRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(tickRef.current);
  }, [running]);

  const requestSimulation = useCallback(() => {
    reset();
    setWsStatus('connecting');
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsStatus('running');
      const payload = { seed, model: selectedModel, baseCode,
        params: { baseArrivalRate, breakdownProb, batchArrivalSize, lunchPenalty } };
      if (selectedPreset !== 'none') payload.preset = selectedPreset;
      ws.send(JSON.stringify(payload));
    };

    ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      if (msg.type === 'snapshots') {
        baselineSnapsRef.current = msg.baseline;
        dahsSnapsRef.current     = msg.dahs;
        if (msg.evaluationLog)    setEvalLog(msg.evaluationLog);
        if (msg.switchingSummary) setSwitchingSummary(msg.switchingSummary);
        if (msg.presetName) setPresetMeta({ name: msg.presetName, favoredHeuristic: msg.presetFavoredHeuristic, whyItFavors: msg.presetWhyItFavors });
        setWsStatus('ready');
        setRunning(true);
      } else if (msg.type === 'error') {
        setWsStatus('error'); setWsError(msg.msg || 'Unknown error');
      }
    };
    ws.onerror = () => { setWsStatus('error'); setWsError('Cannot connect to backend. Is the server running on port 8000?'); };
    ws.onclose = () => { wsRef.current = null; };
  }, [seed, selectedModel, baseCode, selectedPreset, baseArrivalRate, breakdownProb, batchArrivalSize, lunchPenalty, reset]);

  const handleToggle = () => {
    if (wsStatus === 'error' || wsStatus === 'idle') { requestSimulation(); return; }
    if (finished) { reset(); return; }
    if (wsStatus === 'ready') setRunning(r => !r);
  };

  const fm = fifoSnap?.metrics   || {};
  const hm = hybridSnap?.metrics || {};
  const progress = (simTime / 600) * 100;


  return (
    <div className="overflow-x-hidden">

      {/* ── HERO ──────────────────────────────────────────────── */}
      <section className="relative min-h-[36vh] flex items-center justify-center text-center px-6 pt-8 pb-14 overflow-hidden">
        <div className="blob-bg bg-primary/12 w-[55vw] h-[55vh] shape-organic-3 top-[-8vh] left-[-8vw]" />
        <div className="relative z-10 max-w-3xl mx-auto">
          <div className="inline-flex items-center gap-2 px-5 py-2 rounded-full bg-white/70 backdrop-blur border border-border/60 text-primary font-body text-sm font-semibold mb-7 shadow-soft">
            <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
            Live Simulation · Batch-wise Selector · 15-min Re-evaluation
          </div>
          <h1 className="font-heading text-5xl md:text-6xl font-semibold leading-tight text-foreground mb-5 text-balance">
            Watch the Scheduler <span className="italic text-primary">Decide</span>
          </h1>
          <p className="font-body text-lg text-muted-foreground max-w-2xl mx-auto leading-relaxed">
            Both baseline and DAHS 2.0 receive identical job arrivals.
            The evaluation log panel shows every ML decision, guardrail activation,
            and plain-English explanation in real time.
          </p>
        </div>
      </section>

      {/* ── SIMULATION PANEL ─────────────────────────────────── */}
      <section className="pb-8 px-4 md:px-6">
        <div className="max-w-7xl mx-auto">

          {/* Config panel */}
          <div className="mb-5 bg-white/90 backdrop-blur-sm rounded-2xl border border-border/60 shadow-soft overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-border/40 bg-slate-50/70">
              <div className="flex items-center gap-2.5">
                <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center">
                  <BarChart2 size={14} className="text-primary" />
                </div>
                <span className="font-heading text-sm font-semibold">Simulation Configuration</span>
                <span className="px-2 py-0.5 rounded-full bg-slate-100 border border-slate-200 font-body text-[10px] font-bold text-slate-500 uppercase tracking-wider">
                  8 zones · 37 stations · BatchwiseSelector
                </span>
              </div>
              <div className="flex items-center gap-3 text-[10px] font-body text-muted-foreground">
                <span className="flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full" style={{
                    background: wsStatus==='ready'||wsStatus==='running'?'#1E3A8A':wsStatus==='error'?'#DC2626':wsStatus==='connecting'?'#F59E0B':'#94A3B8',
                    animation: wsStatus==='connecting'||wsStatus==='running'?'pulse 1.5s infinite':'none',
                  }} />
                  {wsStatus==='idle'?'Backend idle':wsStatus==='connecting'?'Connecting…':wsStatus==='running'?'Computing…':wsStatus==='ready'?'Live':wsError||'Error'}
                </span>
              </div>
            </div>

            <div className="p-5 flex flex-col gap-4">
              {/* Preset selector */}
              <div className="flex flex-col gap-2">
                <span className="font-body text-[10px] font-bold text-violet-700 uppercase tracking-widest">Scenario Preset</span>
                <div className="flex flex-col sm:flex-row gap-3 items-start">
                  <select
                    value={selectedPreset}
                    onChange={(e) => {
                      setSelectedPreset(e.target.value);
                      if (e.target.value !== 'none') {
                        const p = presets.find(x => x.name === e.target.value);
                        if (p) setBaseCode(
                          p.favored_heuristic === 'fifo' ? 'FIFO' :
                          p.favored_heuristic === 'priority_edd' ? 'EDD' :
                          p.favored_heuristic === 'critical_ratio' ? 'Critical-Ratio' :
                          p.favored_heuristic === 'atc' ? 'ATC' :
                          p.favored_heuristic === 'wspt' ? 'WSPT' :
                          p.favored_heuristic === 'slack' ? 'Slack' : 'FIFO'
                        );
                      }
                    }}
                    className="bg-white border-2 border-violet-300 rounded-lg px-3 py-1.5 font-body text-sm font-semibold text-violet-800 shadow-sm focus:outline-none focus:ring-1 focus:ring-violet-400 transition-colors min-w-[260px]"
                    disabled={running && !finished}
                  >
                    <option value="none">Custom (manual settings)</option>
                    {presets.map(p => (
                      <option key={p.name} value={p.name}>{p.name} — favors {p.favored_heuristic.toUpperCase().replace('_', '-')}</option>
                    ))}
                  </select>
                  {selectedPreset !== 'none' && (() => {
                    const p = presets.find(x => x.name === selectedPreset);
                    if (!p) return null;
                    return (
                      <div className="flex-1 px-3 py-2 rounded-xl bg-violet-50 border border-violet-200 text-xs font-body text-violet-800 leading-snug">
                        <span className="font-bold block mb-0.5">{p.description}</span>
                        <span className="text-violet-600">{p.why_it_favors}</span>
                      </div>
                    );
                  })()}
                </div>
              </div>

              {/* Row 1: selectors */}
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex flex-col gap-1">
                  <label className="font-body text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Scenario Seed</label>
                  <input type="number" min="1" max="99999" value={seed}
                    onChange={e => setSeed(parseInt(e.target.value) || 42)}
                    className="bg-white border border-border/60 rounded-lg px-3 py-1.5 font-mono text-sm w-28 shadow-sm focus:outline-none focus:ring-1 focus:ring-primary/40"
                    disabled={running && !finished}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="font-body text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Baseline vs DAHS</label>
                  <select value={baseCode} onChange={e => setBaseCode(e.target.value)}
                    className="bg-white border border-border/60 rounded-lg px-3 py-1.5 font-body text-sm font-semibold shadow-sm focus:outline-none focus:ring-1 focus:ring-primary/40"
                    disabled={running}
                  >
                    {BASE_STRATEGIES.map(s => <option key={s.code} value={s.code}>{s.name}</option>)}
                  </select>
                </div>
                <div className="flex flex-col gap-1">
                  <label className="font-body text-[10px] font-bold text-primary uppercase tracking-wider">DAHS Model</label>
                  <select value={selectedModel} onChange={e => setSelectedModel(e.target.value)}
                    className="bg-white border-2 border-primary/40 rounded-lg px-3 py-1.5 font-body text-sm font-bold text-primary shadow-sm focus:outline-none focus:ring-1 focus:ring-primary/40"
                    disabled={running}
                  >
                    <option value="dt">Decision Tree</option>
                    <option value="rf">Random Forest</option>
                    <option value="xgb">XGBoost (best)</option>
                    <option value="priority">Hybrid Priority (GBR)</option>
                  </select>
                </div>
              </div>

              {/* Row 2: chaotic parameters */}
              {selectedPreset === 'none' && (
                <div className="flex flex-wrap gap-5 items-end">
                  {[
                    { label: 'Arrival Rate', val: baseArrivalRate, set: setBaseArrivalRate, min: 0.5, max: 6, step: 0.1 },
                    { label: 'Breakdown Prob', val: breakdownProb, set: setBreakdownProb, min: 0, max: 0.05, step: 0.001 },
                    { label: 'Batch Size', val: batchArrivalSize, set: v => setBatchArrivalSize(parseInt(v)||10), min: 5, max: 100, step: 1 },
                    { label: 'Lunch Penalty', val: lunchPenalty, set: setLunchPenalty, min: 0, max: 1, step: 0.05 },
                  ].map(({ label, val, set, min, max, step }) => (
                    <div key={label} className="flex flex-col gap-1">
                      <label className="font-body text-[10px] font-bold text-muted-foreground uppercase tracking-wider">{label}</label>
                      <div className="flex items-center gap-2">
                        <input
                          type="range" min={min} max={max} step={step} value={val}
                          onChange={e => set(parseFloat(e.target.value))}
                          disabled={running && !finished}
                          className="w-24 accent-primary"
                        />
                        <span className="font-mono text-[11px] text-foreground">{typeof val === 'number' ? val.toFixed(step < 0.1 ? 3 : 1) : val}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Controls + progress */}
              <div className="flex items-center gap-3 flex-wrap">
                <button
                  id="sim-run-btn"
                  onClick={handleToggle}
                  disabled={wsStatus === 'connecting' || wsStatus === 'running'}
                  className="flex items-center gap-2 px-6 py-2.5 rounded-full bg-primary text-white font-body font-bold text-sm shadow-soft hover:-translate-y-0.5 hover:shadow-glow active:translate-y-0 transition-all duration-300 disabled:opacity-60"
                >
                  {wsStatus === 'connecting' || wsStatus === 'running' ? (
                    <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/></svg>
                  ) : finished ? (
                    <><RotateCcw size={14}/> Replay</>
                  ) : running ? (
                    <><Pause size={14}/> Pause</>
                  ) : (
                    <><Play size={14}/> Run Simulation</>
                  )}
                </button>

                {wsStatus !== 'idle' && !running && baselineSnapsRef.current.length > 0 && (
                  <button onClick={() => setRunning(true)} className="px-4 py-2 rounded-full border border-border/60 font-body text-sm text-muted-foreground hover:bg-muted transition-colors">
                    <Play size={14} /> Resume
                  </button>
                )}

                {wsStatus !== 'idle' && (
                  <div className="flex-1 flex flex-col gap-1 min-w-[120px]">
                    <div className="flex justify-between text-[10px] font-mono text-muted-foreground">
                      <span>t = {simTime.toFixed(0)} min</span>
                      <span>{progress.toFixed(0)}%</span>
                    </div>
                    <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                      <div className="progress-bar h-full rounded-full" style={{ width: `${progress}%` }} />
                    </div>
                  </div>
                )}

                {wsError && <p className="text-red-500 font-body text-xs">{wsError}</p>}
              </div>

              {/* Guardrail info toast */}
              {switchingSummary?.guardrailActivations > 0 && (
                <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-orange-50 border border-orange-200 text-xs font-body text-orange-800">
                  <Shield size={14} />
                  <span><strong>{switchingSummary.guardrailActivations}</strong> guardrail activation(s) during this simulation. See evaluation log below.</span>
                </div>
              )}
            </div>
          </div>

          {/* Dual canvas */}
          <div className="grid md:grid-cols-2 gap-4 mb-4">
            {[
              { snap: fifoSnap,   label: baseCode,  accent: '#64748B' },
              { snap: hybridSnap, label: 'DAHS 2.0', accent: '#1E3A8A' },
            ].map(({ snap, label, accent }) => (
              <div key={label} className="bg-white rounded-2xl border border-border/50 shadow-soft overflow-hidden">
                <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ background: accent }} />
                  <span className="font-heading text-sm font-semibold text-foreground">{label}</span>
                  {snap?.metrics && (
                    <span className="ml-auto font-body text-[10px] text-muted-foreground">
                      Tardy: {snap.metrics.totalTardiness?.toFixed(0)} | SLA: {(snap.metrics.slaBreachRate * 100).toFixed(1)}%
                    </span>
                  )}
                </div>
                <div style={{ height: '340px' }}>
                  <WarehouseCanvas snapshot={snap} label={label} accentColor={accent} />
                </div>
              </div>
            ))}
          </div>

          {/* Preset meta */}
          {presetMeta && (
            <div className="mb-4 p-4 rounded-2xl bg-violet-50 border border-violet-200">
              <div className="flex items-center gap-3 mb-1">
                <span className="font-body text-xs font-bold text-violet-700 uppercase tracking-wider">{presetMeta.name}</span>
                <span className="font-mono text-xs text-violet-600">Favored: {presetMeta.favoredHeuristic}</span>
              </div>
              <p className="font-body text-xs text-violet-600">{presetMeta.whyItFavors}</p>
            </div>
          )}

          {/* Results metrics */}
          {finished && fifoFinal && hybridFinal && (
            <div className="grid md:grid-cols-2 gap-5 mb-5">
              {[
                { label: 'Total Tardiness', fVal: fifoFinal.totalTardiness, hVal: hybridFinal.totalTardiness, unit: ' min', lower: true },
                { label: 'SLA Breach Rate', fVal: fifoFinal.slaBreachRate * 100, hVal: hybridFinal.slaBreachRate * 100, unit: '%', lower: true },
                { label: 'Avg Cycle Time',  fVal: fifoFinal.avgCycleTime, hVal: hybridFinal.avgCycleTime, unit: ' min', lower: true },
                { label: 'Throughput',      fVal: fifoFinal.throughput, hVal: hybridFinal.throughput, unit: ' /hr', lower: false },
              ].map(({ label, fVal, hVal, unit, lower }) => (
                <div key={label} className="bg-white rounded-2xl border border-border/50 shadow-soft p-5">
                  <MetricBar label={label} baseVal={fVal} dahsVal={hVal} unit={unit} lowerIsBetter={lower} baseLabel={baseCode} />
                </div>
              ))}
            </div>
          )}

          {/* Switching summary */}
          {switchingSummary && switchingSummary.totalEvaluations > 0 && (
            <div className="mb-4 bg-white rounded-2xl border border-border/50 shadow-soft p-5">
              <div className="flex items-center gap-3 mb-4">
                <Brain size={18} className="text-primary" />
                <h3 className="font-heading text-base font-semibold">Batch-wise Selector Summary</h3>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                {[
                  { label: 'Total Evaluations', val: switchingSummary.totalEvaluations, icon: <Clock size={14}/> },
                  { label: 'Switches Made', val: switchingSummary.switchCount, icon: <Zap size={14}/> },
                  { label: 'Hysteresis Blocked', val: switchingSummary.hysteresisBlocked, icon: <Shield size={14}/> },
                  { label: 'Guardrail Activations', val: switchingSummary.guardrailActivations, icon: <Shield size={14}/> },
                ].map(({ label, val, icon }) => (
                  <div key={label} className="text-center p-3 rounded-xl bg-muted/40">
                    <div className="flex justify-center mb-1 text-muted-foreground">{icon}</div>
                    <div className="font-heading text-2xl font-bold text-primary">{val}</div>
                    <div className="font-body text-[11px] text-muted-foreground">{label}</div>
                  </div>
                ))}
              </div>
              <div>
                <p className="font-body text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-2">Heuristic Distribution</p>
                <div className="flex gap-2 flex-wrap">
                  {Object.entries(switchingSummary.distribution || {}).map(([h, frac]) => (
                    <div key={h} className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-primary/5 border border-primary/20">
                      <span className="font-mono text-xs font-bold text-foreground">{h}</span>
                      <span className="font-mono text-xs text-primary">{(frac * 100).toFixed(0)}%</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Evaluation log */}
          {evalLog.length > 0 && (
            <div className="bg-white rounded-2xl border border-border/50 shadow-soft overflow-hidden">
              <button
                id="eval-log-toggle"
                className="w-full flex items-center justify-between px-5 py-4 hover:bg-slate-50 transition-colors"
                onClick={() => setShowLog(o => !o)}
              >
                <div className="flex items-center gap-3">
                  <Brain size={18} className="text-primary" />
                  <span className="font-heading text-base font-semibold">Batch-wise Evaluation Log</span>
                  <span className="badge-new">{evalLog.length} decisions</span>
                </div>
                <ChevronDown size={16} className={`text-muted-foreground transition-transform ${showLog ? 'rotate-180' : ''}`} />
              </button>
              {showLog && (
                <div className="border-t border-border/30 p-4 max-h-[500px] overflow-y-auto space-y-2">
                  {evalLog.map((entry, i) => <EvalEntry key={i} entry={entry} />)}
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
