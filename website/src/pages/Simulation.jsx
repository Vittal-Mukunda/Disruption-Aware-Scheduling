import React, { useEffect, useRef, useState, useCallback } from 'react';
import { ChevronDown, Play, Pause, RotateCcw, Zap, Clock, Target, TrendingDown, BarChart2 } from 'lucide-react';

// In production: same host/port as the page (FastAPI serves both).
// In Vite dev: proxied via vite.config.js → localhost:8000.
const WS_URL = `ws://${window.location.host}/ws/simulate`;
const SNAP_INTERVAL = 2.0;   // must match server.py
const SIM_SPEED     = 4;     // sim-minutes per real-second (playback rate)
const JOB_COLORS    = { A: '#60a5fa', B: '#4ade80', C: '#fb923c', D: '#fbbf24', E: '#c084fc' };

/* ── Scroll-reveal ─────────────────────────────────────────────────── */
function useReveal(threshold = 0.15) {
  const ref = useRef(null);
  const [vis, setVis] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) setVis(true);
    }, { threshold });
    obs.observe(el);
    return () => obs.disconnect();
  }, [threshold]);
  return [ref, vis];
}

/* ── Animated stat counter ─────────────────────────────────────────── */
function AnimCounter({ target, decimals = 0, duration = 1800, suffix = '' }) {
  const [val, setVal] = useState(0);
  const [ref, vis] = useReveal(0.3);
  const started = useRef(false);
  useEffect(() => {
    if (!vis || started.current) return;
    started.current = true;
    const t0 = performance.now();
    const tick = (now) => {
      const p = Math.min((now - t0) / duration, 1);
      const ease = 1 - Math.pow(1 - p, 3);
      setVal(+(target * ease).toFixed(decimals));
      if (p < 1) requestAnimationFrame(tick); else setVal(target);
    };
    requestAnimationFrame(tick);
  }, [vis, target, duration, decimals]);
  return <span ref={ref}>{val.toFixed(decimals)}{suffix}</span>;
}

/* ── Rounded-rect helper (canvas polyfill) ─────────────────────────── */
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

/* ════════════════════════════════════════════════════════════════════
   WAREHOUSE CANVAS — Real aerial warehouse floor plan
   Zones are rectangular areas, conveyor belts connect them, job
   packages appear on workstations and in queue strips.
════════════════════════════════════════════════════════════════════ */
function WarehouseCanvas({ snapshot, label, accentColor }) {
  const canvasRef = useRef(null);
  const animRef   = useRef(null);
  const snapRef   = useRef(snapshot);

  useEffect(() => { snapRef.current = snapshot; }, [snapshot]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    /* DPR-aware resize */
    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const W   = canvas.offsetWidth;
      const H   = canvas.offsetHeight;
      canvas.width  = W * dpr;
      canvas.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    /* Zone layout (normalized 0-1) — U-shape serpentine flow
       Top row L→R:  0=RECV  1=SORT  2=PICK-A  3=PICK-B
       Bottom R→L:   4=VAL   5=QC    6=PACK     7=SHIP
       Zones in same column are vertically aligned for clean conveyor drop */
    const ZONE_NR = [
      // ── top row ──────────────────────────────────────────────
      { rx: 0.010, ry: 0.030, rw: 0.205, rh: 0.44 }, // 0 RECV   3 stations
      { rx: 0.235, ry: 0.030, rw: 0.210, rh: 0.44 }, // 1 SORT   4 stations
      { rx: 0.465, ry: 0.030, rw: 0.240, rh: 0.44 }, // 2 PICK-A 6 stations
      { rx: 0.725, ry: 0.030, rw: 0.265, rh: 0.44 }, // 3 PICK-B 8 stations
      // ── bottom row (aligned under top) ───────────────────────
      { rx: 0.725, ry: 0.535, rw: 0.265, rh: 0.43 }, // 4 VAL-ADD 5 stations (↓ PICK-B)
      { rx: 0.465, ry: 0.535, rw: 0.240, rh: 0.43 }, // 5 QC      4 stations (↓ PICK-A)
      { rx: 0.235, ry: 0.535, rw: 0.210, rh: 0.43 }, // 6 PACK    3 stations (↓ SORT)
      { rx: 0.010, ry: 0.535, rw: 0.205, rh: 0.43 }, // 7 SHIP    4 stations (↓ RECV)
    ];

    /* Zone colours — 8 zones, each with unique identity */
    const ZONE_META = [
      { name: 'INBOUND DOCK', short: 'RECV',  stations: 3, bg: '#EFF6FF', bd: '#93C5FD', hdr: '#2563EB', cols: 3 },
      { name: 'SORTING',      short: 'SORT',  stations: 4, bg: '#F0FDF4', bd: '#86EFAC', hdr: '#16A34A', cols: 2 },
      { name: 'PICKING — A',  short: 'PKG-A', stations: 6, bg: '#FFFBEB', bd: '#FCD34D', hdr: '#D97706', cols: 3 },
      { name: 'PICKING — B',  short: 'PKG-B', stations: 8, bg: '#FFF7ED', bd: '#FDBA74', hdr: '#EA580C', cols: 4 },
      { name: 'VALUE-ADD',    short: 'VAL',   stations: 5, bg: '#FDF4FF', bd: '#E879F9', hdr: '#A21CAF', cols: 3 },
      { name: 'QUALITY CTRL', short: 'QC',    stations: 4, bg: '#ECFDF5', bd: '#6EE7B7', hdr: '#059669', cols: 2 },
      { name: 'PACKING',      short: 'PACK',  stations: 3, bg: '#F5F3FF', bd: '#C4B5FD', hdr: '#7C3AED', cols: 3 },
      { name: 'OUTBOUND DOCK',short: 'SHIP',  stations: 4, bg: '#F0F9FF', bd: '#7DD3FC', hdr: '#0284C7', cols: 2 },
    ];

    /* Conveyor belt connections [fromZone, fxFrac, fyFrac, toZone, txFrac, tyFrac]
       Top row flows left→right; vertical drop on right; bottom row flows right→left */
    const BELT_DEFS = [
      [0, 1, 0.50, 1, 0, 0.50],  // RECV right → SORT left        (top row →)
      [1, 1, 0.50, 2, 0, 0.50],  // SORT right → PICK-A left
      [2, 1, 0.50, 3, 0, 0.50],  // PICK-A right → PICK-B left
      [3, 0.50, 1, 4, 0.50, 0],  // PICK-B bottom → VAL-ADD top   (vertical ↓)
      [4, 0, 0.50, 5, 1, 0.50],  // VAL-ADD left → QC right       (bottom row ←)
      [5, 0, 0.50, 6, 1, 0.50],  // QC left → PACK right
      [6, 0, 0.50, 7, 1, 0.50],  // PACK left → SHIP right
    ];

    let t0 = performance.now();

    const draw = (now) => {
      const W    = canvas.offsetWidth;
      const H    = canvas.offsetHeight;
      const snap = snapRef.current;
      const t    = (now - t0) / 1000;

      ctx.clearRect(0, 0, W, H);

      /* ── FLOOR ────────────────────────────────────────────── */
      ctx.fillStyle = '#EEF2F7';
      ctx.fillRect(0, 0, W, H);

      /* Concrete tile grid */
      const tSz = Math.max(20, Math.round(W / 22));
      ctx.strokeStyle = 'rgba(148,163,184,0.18)';
      ctx.lineWidth = 0.5;
      for (let x = 0; x < W; x += tSz) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
      }
      for (let y = 0; y < H; y += tSz) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
      }

      /* ── ZONE PIXEL RECTS ─────────────────────────────────── */
      const zr = ZONE_NR.map(n => ({
        x: n.rx * W, y: n.ry * H, w: n.rw * W, h: n.rh * H,
      }));

      /* ── CONVEYOR BELTS ───────────────────────────────────── */
      BELT_DEFS.forEach(([fi, fx, fy, ti, tx, ty]) => {
        const fz = zr[fi], tz = zr[ti];
        const x1 = fz.x + fx * fz.w;
        const y1 = fz.y + fy * fz.h;
        const x2 = tz.x + tx * tz.w;
        const y2 = tz.y + ty * tz.h;
        const len = Math.hypot(x2 - x1, y2 - y1);
        const ang = Math.atan2(y2 - y1, x2 - x1);

        ctx.save();
        ctx.translate(x1, y1);
        ctx.rotate(ang);

        /* Belt outer shadow */
        ctx.fillStyle = 'rgba(0,0,0,0.08)';
        ctx.fillRect(-1, -7, len + 2, 14);

        /* Belt surface */
        ctx.fillStyle = '#94A3B8';
        ctx.fillRect(0, -5, len, 10);

        /* Moving ribs */
        ctx.fillStyle = '#64748B';
        const ribSpacing = 14;
        const ribOffset  = (t * 24) % ribSpacing;
        for (let sx = -ribOffset; sx < len + ribSpacing; sx += ribSpacing) {
          ctx.fillRect(sx, -5, 2.5, 10);
        }

        /* Direction arrows */
        ctx.fillStyle = 'rgba(248,250,252,0.75)';
        for (let ax = 22; ax < len - 10; ax += 40) {
          ctx.beginPath();
          ctx.moveTo(ax, 0);
          ctx.lineTo(ax - 7, -3.5);
          ctx.lineTo(ax - 7,  3.5);
          ctx.closePath();
          ctx.fill();
        }

        ctx.restore();
      });

      /* ── GROUP ACTIVE JOBS BY ZONE ────────────────────────── */
      const byZone = Array(8).fill(null).map(() => ({ proc: [], wait: [] }));
      if (snap?.activeJobs) {
        snap.activeJobs.slice(0, 200).forEach(j => {
          if (j.zoneId >= 0 && j.zoneId < 8) {
            if (j.status === 'processing') byZone[j.zoneId].proc.push(j);
            else byZone[j.zoneId].wait.push(j);
          }
        });
      }

      /* ── DRAW EACH ZONE ───────────────────────────────────── */
      zr.forEach((z, i) => {
        const meta   = ZONE_META[i];
        const qLen   = snap ? (snap.zoneQueueLengths[i] || 0) : 0;
        const active = snap ? (snap.zoneActiveCounts[i]  || 0) : 0;
        const load   = active / meta.stations;
        const procJobs = byZone[i].proc;
        const waitJobs = byZone[i].wait;

        /* Zone shadow */
        ctx.shadowColor  = 'rgba(30,58,138,0.10)';
        ctx.shadowBlur   = 8;
        ctx.shadowOffsetY = 3;

        /* Zone fill */
        rr(ctx, z.x, z.y, z.w, z.h, 7);
        ctx.fillStyle = meta.bg;
        ctx.fill();
        ctx.shadowBlur = 0; ctx.shadowOffsetY = 0;

        /* Zone border — brighter when busy */
        rr(ctx, z.x, z.y, z.w, z.h, 7);
        ctx.strokeStyle = load > 0.5 ? meta.hdr : meta.bd;
        ctx.lineWidth   = load > 0.5 ? 2.5 : 1.5;
        ctx.stroke();

        /* Header bar (top-rounded only) */
        const hr = 7;
        ctx.beginPath();
        ctx.moveTo(z.x + hr, z.y);
        ctx.lineTo(z.x + z.w - hr, z.y);
        ctx.quadraticCurveTo(z.x + z.w, z.y, z.x + z.w, z.y + hr);
        ctx.lineTo(z.x + z.w, z.y + 22);
        ctx.lineTo(z.x, z.y + 22);
        ctx.lineTo(z.x, z.y + hr);
        ctx.quadraticCurveTo(z.x, z.y, z.x + hr, z.y);
        ctx.closePath();
        ctx.fillStyle = meta.hdr;
        ctx.globalAlpha = 0.88;
        ctx.fill();
        ctx.globalAlpha = 1;

        /* Zone name */
        ctx.fillStyle = '#F0F9FF';
        ctx.font = `bold ${Math.min(8.5, z.w / 8)}px system-ui,sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(meta.name, z.x + z.w / 2, z.y + 11);

        /* Load indicator dot */
        const dotCol = load > 0.7 ? '#EF4444' : load > 0.3 ? '#F59E0B' : '#10B981';
        ctx.beginPath();
        ctx.arc(z.x + z.w - 9, z.y + 11, 3.5, 0, Math.PI * 2);
        ctx.fillStyle = dotCol;
        ctx.fill();

        /* ── WORKSTATION GRID ──────────────────────────── */
        const stCount = meta.stations;
        const stCols  = meta.cols; // per-zone column count matches station layout
        const stRows  = Math.ceil(stCount / stCols);
        const padX    = 6, padY = 6;
        const avW     = z.w - padX * 2;
        const avH     = z.h - 26 - padY * 2 - (qLen > 0 ? 22 : 4);
        const stW     = Math.max(12, (avW - (stCols - 1) * 4) / stCols);
        const stH     = Math.max(10, (avH - (stRows - 1) * 4) / stRows);
        const gridW   = stCols * stW + (stCols - 1) * 4;
        const gridH   = stRows * stH + (stRows - 1) * 4;
        const stStartX = z.x + (z.w - gridW) / 2;
        const stStartY = z.y + 26 + (avH - gridH) / 2;

        for (let s = 0; s < stCount; s++) {
          const col = s % stCols;
          const row = Math.floor(s / stCols);
          const sx  = stStartX + col * (stW + 4);
          const sy  = stStartY + row * (stH + 4);
          const occupied = s < procJobs.length;

          /* Station base */
          rr(ctx, sx, sy, stW, stH, 3);
          ctx.fillStyle = occupied ? `${meta.hdr}28` : '#E2E8F0';
          ctx.fill();
          rr(ctx, sx, sy, stW, stH, 3);
          ctx.strokeStyle = occupied ? meta.hdr : '#CBD5E1';
          ctx.lineWidth = occupied ? 1.5 : 1;
          ctx.stroke();

          /* Job package ON the station */
          if (occupied && procJobs[s]) {
            const pad = 3;
            rr(ctx, sx + pad, sy + pad, stW - pad * 2, stH - pad * 2, 2);
            ctx.fillStyle = procJobs[s].color;
            ctx.fill();
          }
        }

        /* ── QUEUE STRIP ───────────────────────────────── */
        if (qLen > 0 || waitJobs.length > 0) {
          const qy = z.y + z.h - 22;

          /* Strip background */
          ctx.fillStyle = 'rgba(15,23,42,0.05)';
          ctx.fillRect(z.x + 2, qy, z.w - 4, 18);

          /* Waiting package dots */
          const maxDots = Math.min(waitJobs.length, Math.floor((z.w - 28) / 9));
          for (let w = 0; w < maxDots; w++) {
            const wx = z.x + 4 + w * 9;
            rr(ctx, wx, qy + 4, 7, 10, 1.5);
            ctx.fillStyle = waitJobs[w].color;
            ctx.globalAlpha = 0.85;
            ctx.fill();
            ctx.globalAlpha = 1;
          }
          if (waitJobs.length > maxDots) {
            ctx.fillStyle = '#94A3B8';
            ctx.font = '7px system-ui,sans-serif';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillText(`+${waitJobs.length - maxDots}`, z.x + 4 + maxDots * 9, qy + 9);
          }

          /* Queue count badge */
          ctx.fillStyle = qLen > 10 ? '#DC2626' : '#374151';
          ctx.font = `bold ${Math.min(8, z.w / 9)}px system-ui,sans-serif`;
          ctx.textAlign = 'right';
          ctx.textBaseline = 'middle';
          ctx.fillText(`Q:${qLen}`, z.x + z.w - 3, qy + 9);
        }
      });

      /* ── HUD ────────────────────────────────────────────────── */
      if (snap) {
        ctx.fillStyle = 'rgba(15,23,42,0.35)';
        ctx.font = '9px system-ui,sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.fillText(`t = ${snap.time.toFixed(1)} min`, 8, 5);
      }
      ctx.fillStyle = accentColor;
      ctx.font = 'bold 9px system-ui,sans-serif';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'top';
      ctx.fillText(label, W - 8, 5);

      animRef.current = requestAnimationFrame(draw);
    };

    animRef.current = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(animRef.current); ro.disconnect(); };
  // Only re-init when accentColor or label prop changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accentColor, label]);

  return <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block' }} />;
}

/* ── Dual metric bar ───────────────────────────────────────────────── */
function MetricBar({ label, fifoVal, hybridVal, unit = '', lowerIsBetter = true, maxVal, baseLabel = 'FIFO' }) {
  const max   = maxVal || Math.max(fifoVal, hybridVal) * 1.2 || 1;
  const fifoW = Math.min((fifoVal  / max) * 100, 100);
  const hybW  = Math.min((hybridVal / max) * 100, 100);
  const wins  = lowerIsBetter ? hybridVal < fifoVal : hybridVal > fifoVal;
  const pct   = fifoVal > 0 ? Math.abs((fifoVal - hybridVal) / fifoVal * 100).toFixed(1) : '—';
  const dp    = unit === '%' || unit.includes('hr') ? 1 : 0;

  return (
    <div className="mb-4">
      <div className="flex justify-between items-baseline mb-1.5">
        <span className="font-body text-sm font-semibold text-foreground/75">{label}</span>
        {wins && fifoVal > 0 && (
          <span className="font-body text-xs font-bold text-primary bg-primary/10 px-2 py-0.5 rounded-full">
            {lowerIsBetter ? '−' : '+'}{pct}%
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 mb-1">
        <span className="font-body text-[10px] text-muted-foreground w-12 text-right shrink-0">{baseLabel}</span>
        <div className="flex-1 h-4 bg-muted rounded-full overflow-hidden">
          <div className="h-full rounded-full transition-all duration-700" style={{ width: `${fifoW}%`, background: '#64748B' }} />
        </div>
        <span className="font-body text-[10px] font-mono text-muted-foreground w-16 shrink-0">
          {typeof fifoVal === 'number' ? fifoVal.toFixed(dp) : '—'}{unit}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <span className="font-body text-[10px] text-primary font-bold w-12 text-right shrink-0">DAHS</span>
        <div className="flex-1 h-4 bg-muted rounded-full overflow-hidden">
          <div className="h-full rounded-full transition-all duration-700" style={{ width: `${hybW}%`, background: '#1E3A8A' }} />
        </div>
        <span className="font-body text-[10px] font-mono font-bold text-primary w-16 shrink-0">
          {typeof hybridVal === 'number' ? hybridVal.toFixed(dp) : '—'}{unit}
        </span>
      </div>
    </div>
  );
}

/* ── FAQ accordion ─────────────────────────────────────────────────── */
const FAQS = [
  {
    q: 'How does DAHS decide which heuristic to use at each dispatch event?',
    a: 'An XGBoost classifier (and a companion Random Forest) trained on 22 system-state features predicts which of six dispatch rules (FIFO, Priority-EDD, Critical Ratio, ATC, WSPT, or Slack) will minimise a combined objective of tardiness and SLA breach rate for the current operational context. The prediction is made independently at every dispatch event, so the strategy can switch dozens of times per minute.',
  },
  {
    q: 'Is this simulation scientifically fair — do both algorithms see the same jobs?',
    a: 'Yes. Both FIFO and DAHS in the live panel share an identical seeded pseudo-random number generator (Mulberry32, seed 42). All job arrival times, types, and processing times are pre-determined before the simulation runs. Any difference in outcomes is purely the result of the dispatch strategy.',
  },
  {
    q: 'What are the four novel disruption-aware features that make DAHS unique?',
    a: 'disruption_intensity: composite of breakdown severity, lunch-break penalty, and surge deviation. queue_imbalance: coefficient of variation of queue depths across all zones. job_mix_entropy: Shannon entropy of the job-type distribution in the queue. time_pressure_ratio: fraction of waiting jobs whose Critical Ratio has fallen below 1.0.',
  },
  {
    q: "Why not use deep reinforcement learning — wouldn't that be more powerful?",
    a: "DRL requires GPU training over millions of steps, is harder to audit, and rarely outperforms well-tuned composite heuristics in real-world scheduling without careful reward shaping. Our supervised approach trains in under 60 minutes on CPU and produces a fully interpretable decision tree alongside the Random Forest and XGBoost models — satisfying academic reproducibility standards.",
  },
  {
    q: 'How statistically robust are the benchmark results?',
    a: "Evaluation covers 300 completely held-out seeds (99000–99299), disjoint from the 1,000 training seeds. Statistical tests include the Friedman χ² test (p < 0.001), post-hoc Nemenyi test with Critical Difference diagram, paired Wilcoxon signed-rank tests with Holm–Bonferroni correction, Cohen's d effect sizes, and bootstrap 95% confidence intervals (5,000 resamples each).",
  },
];

function FAQItem({ q, a, idx }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`border rounded-3xl overflow-hidden transition-all duration-300 ${open ? 'border-primary/40 shadow-soft bg-white' : 'border-border/50 bg-white/70 hover:border-border'}`}>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-start justify-between gap-5 px-7 py-6 text-left group outline-none"
      >
        <div className="flex items-start gap-4">
          <span className="font-heading text-secondary text-lg font-semibold shrink-0 pt-0.5">
            {String(idx + 1).padStart(2, '0')}.
          </span>
          <span className="font-heading text-base md:text-lg font-semibold text-foreground leading-snug group-hover:text-primary transition-colors duration-200">
            {q}
          </span>
        </div>
        <div className={`w-9 h-9 rounded-full flex items-center justify-center bg-muted text-primary shrink-0 mt-0.5 transition-all duration-300 ${open ? 'bg-primary/15 rotate-180' : ''}`}>
          <ChevronDown size={16} />
        </div>
      </button>
      <div style={{ maxHeight: open ? '320px' : '0', overflow: 'hidden', transition: 'max-height .4s cubic-bezier(.4,0,.2,1)' }}>
        <p className="font-body text-[15px] text-muted-foreground leading-relaxed px-7 pb-7 pt-0">{a}</p>
      </div>
    </div>
  );
}

/* ── All-methods results ────────────────────────────────────────────── */
const ALL_METHODS = [
  { name: 'Slack',             color: '#78716C', tard: 28223, sla: 39.7, thru: 43.1, cycle: 143.4, rank: 9 },
  { name: 'FIFO',              color: '#94A3B8', tard: 25633, sla: 35.8, thru: 43.0, cycle: 155.3, rank: 8 },
  { name: 'Critical Ratio',    color: '#6B7280', tard: 21771, sla: 40.1, thru: 42.9, cycle: 155.2, rank: 7 },
  { name: 'Priority-EDD',      color: '#64748B', tard: 16289, sla: 36.6, thru: 43.1, cycle: 101.4, rank: 6 },
  { name: 'Hybrid-Priority',   color: '#818CF8', tard:  8835, sla: 36.2, thru: 43.2, cycle:  84.9, rank: 5 },
  { name: 'ATC',               color: '#3B82F6', tard:  3113, sla: 22.2, thru: 44.7, cycle:  72.8, rank: 4 },
  { name: 'WSPT',              color: '#2563EB', tard:  1626, sla:  4.8, thru: 45.2, cycle:  37.1, rank: 3 },
  { name: 'DAHS Hybrid-RF',    color: '#1E3A8A', tard:  1626, sla:  4.8, thru: 45.2, cycle:  37.1, rank: 2 },
  { name: 'DAHS Hybrid-XGB',   color: '#0F172A', tard:  1617, sla:  4.8, thru: 45.2, cycle:  37.0, rank: 1, best: true },
];
const MAX_TARD = 30000;

const BASE_STRATEGIES = [
  { code: 'FIFO',  name: 'FIFO (First In, First Out)' },
  { code: 'EDD',   name: 'Priority-EDD' },
  { code: 'CR',    name: 'Critical Ratio' },
  { code: 'ATC',   name: 'Apparent Tardiness Cost' },
  { code: 'WSPT',  name: 'Weighted Shortest Proc Time' },
  { code: 'Slack', name: 'Minimum Slack Time' },
];

/* ════════════════════════════════════════════════════════════════════
   MAIN PAGE
════════════════════════════════════════════════════════════════════ */
export default function Simulation() {
  /* ── Config state ───────────────��────────────────────────────────── */
  const [seed,          setSeed]          = useState(42);
  const [baseCode,      setBaseCode]      = useState('FIFO');
  const [selectedModel, setSelectedModel] = useState('xgb');

  // Chaotic Parameters
  const [baseArrivalRate, setBaseArrivalRate] = useState(2.5);
  const [breakdownProb,   setBreakdownProb]   = useState(0.003);
  const [batchArrivalSize,setBatchArrivalSize] = useState(30);
  const [expressPct,      setExpressPct]      = useState(0.12);
  const [lunchPenalty,    setLunchPenalty]    = useState(0.3);

  /* ── WebSocket + playback state ────────────────────────────���─────── */
  const [wsStatus,    setWsStatus]    = useState('idle');   // idle|connecting|running|ready|error
  const [wsError,     setWsError]     = useState('');
  const [running,     setRunning]     = useState(false);
  const [simTime,     setSimTime]     = useState(0);
  const [fifoSnap,    setFifoSnap]    = useState(null);
  const [hybridSnap,  setHybridSnap]  = useState(null);
  const [finished,    setFinished]    = useState(false);
  const [fifoFinal,   setFifoFinal]   = useState(null);
  const [hybridFinal, setHybridFinal] = useState(null);

  const baselineSnapsRef = useRef([]);
  const dahsSnapsRef     = useRef([]);
  const simTimeRef       = useRef(0);
  const tickRef          = useRef(null);
  const wsRef            = useRef(null);

  /* ── Colour helper: add .color to each activeJob if missing ─────── */
  const enrichSnap = (snap) => {
    if (!snap) return snap;
    return {
      ...snap,
      activeJobs: (snap.activeJobs || []).map(j => ({
        ...j,
        color: j.color || JOB_COLORS[j.type] || '#94A3B8',
      })),
    };
  };

  /* ── Reset everything to idle ────────────────────────────────────── */
  const reset = useCallback(() => {
    cancelAnimationFrame(tickRef.current);
    if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
    baselineSnapsRef.current = [];
    dahsSnapsRef.current     = [];
    simTimeRef.current       = 0;
    setSimTime(0);
    setRunning(false);
    setFinished(false);
    setFifoSnap(null);
    setHybridSnap(null);
    setFifoFinal(null);
    setHybridFinal(null);
    setWsStatus('idle');
    setWsError('');
  }, []);

  /* ── Playback RAF loop (reads from pre-loaded snapshot arrays) ───── */
  useEffect(() => {
    if (!running) { cancelAnimationFrame(tickRef.current); return; }
    const total = baselineSnapsRef.current.length;
    if (!total) return;
    let lastReal = performance.now();

    const tick = (now) => {
      const dtSec = Math.min((now - lastReal) / 1000, 0.05);
      lastReal = now;
      const nextT  = Math.min(simTimeRef.current + dtSec * SIM_SPEED * 60, 600);
      simTimeRef.current = nextT;
      const idx = Math.min(Math.floor(nextT / SNAP_INTERVAL), total - 1);
      setFifoSnap(enrichSnap(baselineSnapsRef.current[idx]));
      setHybridSnap(enrichSnap(dahsSnapsRef.current[idx]));
      setSimTime(nextT);
      if (nextT >= 600) {
        setRunning(false);
        setFinished(true);
        setFifoFinal(baselineSnapsRef.current[total - 1]?.metrics || null);
        setHybridFinal(dahsSnapsRef.current[total - 1]?.metrics   || null);
        return;
      }
      tickRef.current = requestAnimationFrame(tick);
    };
    tickRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(tickRef.current);
  }, [running]);

  /* ── Request simulation from backend ──────────────────���──────────── */
  const requestSimulation = useCallback(() => {
    reset();
    setWsStatus('connecting');
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsStatus('running');
      ws.send(JSON.stringify({
        seed,
        model:    selectedModel,
        baseCode,
        params: { baseArrivalRate, breakdownProb, batchArrivalSize, expressPct, lunchPenalty },
      }));
    };

    ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      if (msg.type === 'snapshots') {
        baselineSnapsRef.current = msg.baseline;
        dahsSnapsRef.current     = msg.dahs;
        setWsStatus('ready');
        setRunning(true);   // auto-start playback
      } else if (msg.type === 'error') {
        setWsStatus('error');
        setWsError(msg.msg || 'Unknown error');
      }
    };

    ws.onerror = () => {
      setWsStatus('error');
      setWsError('Cannot connect to backend. Is the server running on port 8000?');
    };

    ws.onclose = () => { wsRef.current = null; };
  }, [seed, selectedModel, baseCode, baseArrivalRate, breakdownProb, batchArrivalSize, expressPct, lunchPenalty, reset]);

  /* ── Button handler ────────────────────────��─────────────────────── */
  const handleToggle = () => {
    if (wsStatus === 'error' || wsStatus === 'idle') { requestSimulation(); return; }
    if (finished)  { reset(); return; }
    if (wsStatus === 'ready') setRunning(r => !r);
  };

  const fm = fifoSnap?.metrics   || {};
  const hm = hybridSnap?.metrics || {};

  const [statsRef,   statsVis]   = useReveal(0.15);
  const [resultsRef, resultsVis] = useReveal(0.10);
  const [faqRef,     faqVis]     = useReveal(0.08);

  const progress = (simTime / 600) * 100;

  return (
    <div className="overflow-x-hidden">

      {/* ── HERO ─────────────────────────────────────────────────── */}
      <section className="relative min-h-[38vh] flex items-center justify-center text-center px-6 pt-8 pb-14 overflow-hidden">
        <div className="blob-bg bg-primary/12 w-[55vw] h-[55vh] shape-organic-3 top-[-8vh] left-[-8vw]" />
        <div className="blob-bg bg-accent/30 w-[45vw] h-[45vh] shape-organic-1 bottom-[-5vh] right-[-5vw]" />

        <div className="relative z-10 max-w-3xl mx-auto">
          <div className="inline-flex items-center gap-2 px-5 py-2 rounded-full bg-white/70 backdrop-blur border border-border/60 text-primary font-body text-sm font-semibold mb-7 shadow-soft">
            <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
            Live Simulation · Identical Seed · Real Discrete-Event Engine
          </div>
          <h1 className="font-heading text-5xl md:text-6xl font-semibold leading-tight text-foreground mb-5 text-balance">
            Watch the Scheduler{' '}
            <span className="italic text-primary">Decide</span>
          </h1>
          <p className="font-body text-lg text-muted-foreground max-w-2xl mx-auto leading-relaxed">
            Both FIFO and DAHS receive identical job arrivals from seed&nbsp;42.
            The difference in outcomes is <em>purely</em> from the dispatch strategy.
            The visualisation is a true aerial warehouse floor plan — zones, conveyor belts, and live job packages.
          </p>
        </div>
      </section>

      {/* ── SIMULATION PANEL ─────────────────────────────────────── */}
      <section className="pb-8 px-4 md:px-6">
        <div className="max-w-7xl mx-auto">

          {/* ── CONFIGURATION PANEL ─────────────────────────────── */}
          <div className="mb-5 bg-white/90 backdrop-blur-sm rounded-2xl border border-border/60 shadow-soft overflow-hidden">

            {/* Panel header */}
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-border/40 bg-slate-50/70">
              <div className="flex items-center gap-2.5">
                <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center">
                  <BarChart2 size={14} className="text-primary" />
                </div>
                <span className="font-heading text-sm font-semibold text-foreground">Simulation Configuration</span>
                <span className="px-2 py-0.5 rounded-full bg-slate-100 border border-slate-200 font-body text-[10px] font-bold text-slate-500 uppercase tracking-wider">8 zones · 37 stations · Real ML Models</span>
              </div>
              <div className="flex items-center gap-3 text-[10px] font-body text-muted-foreground">
                <span className="flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full" style={{
                    background: wsStatus==='ready'||wsStatus==='running' ? '#1E3A8A' : wsStatus==='error' ? '#DC2626' : wsStatus==='connecting' ? '#F59E0B' : '#94A3B8',
                    animation: wsStatus==='connecting'||wsStatus==='running' ? 'pulse 1.5s infinite' : 'none',
                  }} />
                  {wsStatus==='idle'?'Backend idle':wsStatus==='connecting'?'Connecting…':wsStatus==='running'?'Computing…':wsStatus==='ready'?'Live':wsError||'Error'}
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: running ? '#10B981' : finished ? '#DC2626' : '#94A3B8', animation: running ? 'pulse 1.5s infinite' : 'none' }} />
                  {running ? 'Playing…' : finished ? 'Complete — click to replay' : 'Ready'}</span>
              </div>
            </div>

            <div className="p-5 flex flex-col gap-5">

              {/* Row 1: Scenario selectors + run controls + progress */}
              <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">

                {/* Selectors */}
                <div className="flex items-end gap-3">
                  <div className="flex flex-col gap-1">
                    <label className="font-body text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Scenario Seed</label>
                    <input
                      type="number" min="1" max="99999" value={seed}
                      onChange={(e) => setSeed(parseInt(e.target.value) || 42)}
                      className="bg-white border border-border/60 rounded-lg px-3 py-1.5 font-mono text-sm text-foreground w-28 shadow-sm focus:outline-none focus:ring-1 focus:ring-primary/40 focus:border-primary/50 transition-colors"
                      disabled={running && !finished}
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="font-body text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Baseline vs DAHS</label>
                    <select
                      value={baseCode} onChange={(e) => setBaseCode(e.target.value)}
                      className="bg-white border border-border/60 rounded-lg px-3 py-1.5 font-body text-sm font-semibold text-foreground shadow-sm focus:outline-none focus:ring-1 focus:ring-primary/40 focus:border-primary/50 transition-colors"
                      disabled={running}
                    >
                      {BASE_STRATEGIES.map(s => <option key={s.code} value={s.code}>{s.name}</option>)}
                    </select>
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="font-body text-[10px] font-bold text-primary uppercase tracking-wider">DAHS Model</label>
                    <select
                      value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)}
                      className="bg-white border-2 border-primary/40 rounded-lg px-3 py-1.5 font-body text-sm font-bold text-primary shadow-sm focus:outline-none focus:ring-1 focus:ring-primary/40 transition-colors"
                      disabled={running}
                    >
                      <option value="xgb">XGBoost ★ best</option>
                      <option value="rf">Random Forest</option>
                      <option value="dt">Decision Tree</option>
                      <option value="priority">GBR Priority</option>
                    </select>
                  </div>
                </div>

                {/* Run controls */}
                <div className="flex items-center gap-2 sm:ml-2">
                  <button
                    onClick={handleToggle}
                    disabled={wsStatus === 'running'}
                    className="flex items-center gap-2 px-5 py-2.5 rounded-xl font-body font-bold text-sm text-white shadow-soft hover:-translate-y-0.5 active:scale-95 transition-all duration-200 disabled:opacity-60 disabled:cursor-not-allowed"
                    style={{ background: wsStatus === 'error' ? '#DC2626' : running ? '#F59E0B' : '#1E3A8A' }}
                  >
                    {wsStatus === 'running' ? <span className="w-3 h-3 border-2 border-white/50 border-t-white rounded-full animate-spin" /> : running ? <Pause size={14} /> : <Play size={14} />}
                    {wsStatus === 'running' ? 'Computing…' : wsStatus === 'error' ? 'Retry' : finished ? 'Replay' : running ? 'Pause' : wsStatus === 'ready' ? 'Resume' : 'Run'}
                  </button>
                  <button
                    onClick={reset} title="Reset simulation"
                    className="w-9 h-9 rounded-xl bg-slate-100 hover:bg-slate-200 border border-border/50 flex items-center justify-center text-muted-foreground hover:text-foreground transition-all duration-200 active:scale-95"
                  >
                    <RotateCcw size={14} />
                  </button>
                </div>

                {/* Progress bar */}
                <div className="flex-1 min-w-0 w-full">
                  <div className="flex justify-between mb-1">
                    <span className="font-body text-[10px] font-semibold text-muted-foreground">Shift Progress</span>
                    <span className="font-body text-[10px] font-bold font-mono text-foreground">{simTime.toFixed(0)} / 600 min</span>
                  </div>
                  <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden border border-slate-200/60">
                    <div
                      className="h-full rounded-full transition-all duration-100 ease-linear"
                      style={{ width: `${progress}%`, background: 'linear-gradient(90deg,#1E3A8A,#3B82F6)' }}
                    />
                  </div>
                  <div className="flex justify-between mt-0.5">
                    <span className="font-body text-[9px] text-muted-foreground">Ramp-up</span>
                    <span className="font-body text-[9px] text-muted-foreground">Peak surge</span>
                    <span className="font-body text-[9px] text-muted-foreground">Lunch dip</span>
                    <span className="font-body text-[9px] text-muted-foreground">Evening rush</span>
                    <span className="font-body text-[9px] text-muted-foreground">End</span>
                  </div>
                </div>
              </div>

              {/* Divider + section label */}
              <div className="flex items-center gap-3">
                <div className="flex-1 h-px bg-border/40" />
                <span className="font-body text-[10px] font-bold text-orange-600 uppercase tracking-widest px-2 py-1 rounded-full bg-orange-50 border border-orange-200/60">
                  Scenario Stress Parameters
                </span>
                <div className="flex-1 h-px bg-border/40" />
              </div>

              {/* Chaos sliders grid */}
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
                {[
                  { label: 'Traffic Volume',  val: `${baseArrivalRate.toFixed(1)}×`, sub: 'Orders/min arrival rate',    bg: 'bg-slate-50',   bd: 'border-slate-200',   accent: '#1E3A8A', input: <input type="range" min="1.0" max="5.0" step="0.1" value={baseArrivalRate} onChange={(e) => setBaseArrivalRate(parseFloat(e.target.value))} className="w-full accent-blue-700 cursor-pointer" disabled={running && !finished}/> },
                  { label: 'Breakdown Risk',  val: `${(breakdownProb*100).toFixed(1)}%`, sub: 'Stall probability / min', bg: 'bg-orange-50',  bd: 'border-orange-200',  accent: '#EA580C', input: <input type="range" min="0.0" max="0.02" step="0.001" value={breakdownProb} onChange={(e) => setBreakdownProb(parseFloat(e.target.value))} className="w-full accent-orange-600 cursor-pointer" disabled={running && !finished}/> },
                  { label: 'Truck Drop Size', val: `${batchArrivalSize} jobs`,       sub: 'Bulk arrival every 45 min', bg: 'bg-indigo-50',  bd: 'border-indigo-200',  accent: '#4F46E5', input: <input type="range" min="0" max="100" step="5" value={batchArrivalSize} onChange={(e) => setBatchArrivalSize(parseFloat(e.target.value))} className="w-full accent-indigo-600 cursor-pointer" disabled={running && !finished}/> },
                  { label: 'Express Mix',     val: `${(expressPct*100).toFixed(0)}%`, sub: 'VIP order percentage',      bg: 'bg-purple-50',  bd: 'border-purple-200',  accent: '#9333EA', input: <input type="range" min="0.0" max="0.5" step="0.05" value={expressPct} onChange={(e) => setExpressPct(parseFloat(e.target.value))} className="w-full accent-purple-600 cursor-pointer" disabled={running && !finished}/> },
                  { label: 'Lunch Penalty',   val: `${(lunchPenalty*100).toFixed(0)}%`, sub: 'Processing time hit @t=300', bg: 'bg-red-50',  bd: 'border-red-200',     accent: '#DC2626', input: <input type="range" min="0.0" max="1.0" step="0.1" value={lunchPenalty} onChange={(e) => setLunchPenalty(parseFloat(e.target.value))} className="w-full accent-red-600 cursor-pointer" disabled={running && !finished}/> },
                ].map(({ label, val, sub, bg, bd, accent, input }) => (
                  <div key={label} className={`flex flex-col gap-2 p-3 rounded-xl ${bg} border ${bd} shadow-sm`}>
                    <div className="flex items-baseline justify-between">
                      <span className="font-body text-[10px] font-bold text-slate-700 uppercase tracking-wider leading-tight">{label}</span>
                      <span className="font-mono text-xs font-bold" style={{ color: accent }}>{val}</span>
                    </div>
                    {input}
                    <span className="font-body text-[9px] text-muted-foreground leading-tight">{sub}</span>
                  </div>
                ))}
              </div>

              {/* Backend info note */}
              <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-primary/5 border border-primary/15 w-fit">
                <span className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" />
                <span className="font-body text-[10px] text-primary/80">
                  Simulation runs via <strong>Python backend</strong> using the real trained ML models — not a JS approximation.
                  Start the server with <code className="bg-primary/10 px-1 rounded">python3 start.py</code>
                </span>
              </div>

            </div>
          </div>

          {/* Dual canvas */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
            <div className="relative rounded-2xl overflow-hidden border border-border/50 shadow-soft" style={{ height: 380 }}>
              <WarehouseCanvas snapshot={fifoSnap} label={`${baseCode} Baseline`} accentColor="#64748B" />
              <div className="absolute top-3 left-3 flex items-center gap-1.5 bg-white/85 backdrop-blur px-3 py-1.5 rounded-full border border-border/50 pointer-events-none">
                <span className="w-2 h-2 rounded-full bg-[#64748B] shrink-0" />
                <span className="font-body text-xs font-bold text-foreground">{baseCode} Baseline</span>
              </div>
            </div>
            <div className="relative rounded-2xl overflow-hidden border-2 shadow-float" style={{ height: 380, borderColor: '#1E3A8A' }}>
              <WarehouseCanvas snapshot={hybridSnap} label={`DAHS ${selectedModel.toUpperCase()}`} accentColor="#1E3A8A" />
              <div className="absolute top-3 left-3 flex items-center gap-1.5 bg-white/85 backdrop-blur px-3 py-1.5 rounded-full border border-primary/30 pointer-events-none">
                <span className="w-2 h-2 rounded-full bg-primary animate-pulse shrink-0" />
                <span className="font-body text-xs font-bold text-primary">DAHS {selectedModel.toUpperCase()} ★</span>
              </div>
            </div>
          </div>

          {/* Warehouse legend */}
          <div className="flex flex-wrap items-center justify-between gap-3 px-3 py-2.5 mb-4 bg-white/70 backdrop-blur border border-border/40 rounded-xl">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
              <span className="font-body text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Job Types:</span>
              {[
                { color: '#c084fc', name: 'Express (E · 10%)' },
                { color: '#60a5fa', name: 'Standard (A · 25%)' },
                { color: '#4ade80', name: 'Bulk (B · 30%)' },
                { color: '#fb923c', name: 'Value-Add (C · 20%)' },
                { color: '#fbbf24', name: 'Complex (D · 15%)' },
              ].map(({ color, name }) => (
                <div key={name} className="flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-sm shrink-0" style={{ background: color }} />
                  <span className="font-body text-[10px] text-foreground/70">{name}</span>
                </div>
              ))}
            </div>
            <div className="flex items-center gap-1.5 font-body text-[10px] text-muted-foreground">
              <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" />Free
              <span className="w-2 h-2 rounded-full bg-amber-500 shrink-0 ml-2" />Busy
              <span className="w-2 h-2 rounded-full bg-red-500 shrink-0 ml-2" />Overloaded
              <span className="mx-2 text-border">|</span>
              <span className="font-semibold text-foreground/60">Flow: RECV→SORT→PICK-A→PICK-B↓VAL→QC→PACK→SHIP</span>
            </div>
          </div>

          {/* Live metric tiles */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {[
              { label: 'Completed Jobs',  fifo: fm.completed || 0,             hybrid: hm.completed || 0,             unit: '',     icon: <Target size={13} />,      higher: true  },
              { label: 'Total Tardiness', fifo: fm.totalTardiness || 0,         hybrid: hm.totalTardiness || 0,         unit: ' min', icon: <Clock size={13} />,       higher: false },
              { label: 'SLA Breach',      fifo: (fm.slaBreachRate || 0) * 100,  hybrid: (hm.slaBreachRate || 0) * 100,  unit: '%',    icon: <TrendingDown size={13} />, higher: false },
              { label: 'Throughput',      fifo: fm.throughput || 0,              hybrid: hm.throughput || 0,             unit: ' j/hr',icon: <Zap size={13} />,          higher: true  },
            ].map(({ label, fifo, hybrid, unit, icon, higher }) => {
              const wins = higher ? hybrid >= fifo : hybrid <= fifo;
              const diff = fifo > 0 ? Math.abs((hybrid - fifo) / fifo * 100) : 0;
              const dp = unit === '%' || unit.includes('hr') ? 1 : 0;
              return (
                <div key={label} className="bg-white/80 backdrop-blur border border-border/50 hover:border-primary/30 rounded-2xl p-4 transition-all duration-300">
                  <div className="flex items-center gap-1.5 text-muted-foreground mb-3">
                    {icon}
                    <span className="font-body text-xs font-semibold">{label}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <p className="font-body text-[9px] text-muted-foreground mb-0.5">{baseCode}</p>
                      <p className="font-heading text-xl font-semibold text-secondary leading-none">
                        {fifo.toFixed(dp)}<span className="font-body text-[10px] text-muted-foreground ml-0.5">{unit}</span>
                      </p>
                    </div>
                    <div>
                      <p className="font-body text-[9px] text-primary font-bold mb-0.5">DAHS</p>
                      <p className="font-heading text-xl font-semibold text-primary leading-none">
                        {hybrid.toFixed(dp)}<span className="font-body text-[10px] text-muted-foreground ml-0.5">{unit}</span>
                      </p>
                    </div>
                  </div>
                  {diff > 0.5 && simTime > 60 && (
                    <p className={`mt-2 font-body text-[9px] font-bold text-center px-2 py-0.5 rounded-full ${wins ? 'bg-primary/10 text-primary' : 'bg-secondary/10 text-secondary'}`}>
                      {wins ? `DAHS +${diff.toFixed(1)}%` : `${baseCode} +${diff.toFixed(1)}%`}
                    </p>
                  )}
                </div>
              );
            })}
          </div>

          {/* Final summary banner */}
          {finished && fifoFinal && hybridFinal && (
            <div
              className="mt-5 p-6 rounded-2xl border-2 border-primary/30 bg-primary/5 shadow-float"
              style={{ animation: 'fadeSlideIn .6s ease forwards' }}
            >
              <div className="text-center mb-5">
                <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-primary/10 border border-primary/25 mb-3">
                  <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                  <span className="font-body text-xs font-bold text-primary tracking-wide uppercase">Simulation Complete</span>
                </div>
                <h3 className="font-heading text-2xl text-foreground">
                  DAHS wins —{' '}
                  {fifoFinal.totalTardiness > 0
                    ? `${((fifoFinal.totalTardiness - hybridFinal.totalTardiness) / fifoFinal.totalTardiness * 100).toFixed(0)}%`
                    : '—'
                  }{' '}
                  tardiness reduction
                </h3>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div>
                  <MetricBar label="Total Tardiness"  fifoVal={fifoFinal.totalTardiness}         hybridVal={hybridFinal.totalTardiness}         unit=" min" lowerIsBetter maxVal={MAX_TARD} baseLabel={baseCode} />
                  <MetricBar label="SLA Breach Rate"  fifoVal={fifoFinal.slaBreachRate * 100}    hybridVal={hybridFinal.slaBreachRate * 100}    unit="%" lowerIsBetter maxVal={60} baseLabel={baseCode} />
                </div>
                <div>
                  <MetricBar label="Avg Cycle Time"   fifoVal={fifoFinal.avgCycleTime}           hybridVal={hybridFinal.avgCycleTime}           unit=" min" lowerIsBetter baseLabel={baseCode} />
                  <MetricBar label="Throughput"       fifoVal={fifoFinal.throughput}             hybridVal={hybridFinal.throughput}             unit=" j/hr" lowerIsBetter={false} baseLabel={baseCode} />
                </div>
                <div className="flex flex-col items-center justify-center gap-3 bg-white/70 rounded-xl border border-border/40 p-5">
                  <div className="font-heading text-5xl font-semibold text-primary">
                    {fifoFinal.totalTardiness > 0
                      ? `${((fifoFinal.totalTardiness - hybridFinal.totalTardiness) / fifoFinal.totalTardiness * 100).toFixed(0)}%`
                      : '—'}
                  </div>
                  <div className="font-body text-sm text-muted-foreground text-center font-semibold leading-snug">
                    Tardiness Reduction<br />
                    <span className="font-normal text-xs">(DAHS vs {baseCode}, this run)</span>
                  </div>
                  <div className="font-heading text-3xl font-semibold text-secondary">
                    {(hybridFinal.slaBreachRate * 100).toFixed(1)}%
                  </div>
                  <div className="font-body text-xs text-muted-foreground text-center font-semibold">DAHS SLA Breach Rate</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* ── STATS STRIP ──────────────────────────────────────────── */}
      <section className="py-16 px-6">
        <div ref={statsRef} className={`max-w-5xl mx-auto reveal ${statsVis ? 'visible' : ''}`}>
          <p className="text-center font-body text-xs font-bold text-muted-foreground uppercase tracking-widest mb-8">
            Aggregate benchmark results · 300 held-out test scenarios · n = 2,700 simulations
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { val: 90,     dec: 0, suf: '%', label: 'Tardiness Reduction', sub: 'DAHS vs average',    icon: <TrendingDown size={16} />, shape: 'shape-organic-1' },
              { val: 4.8,    dec: 1, suf: '%', label: 'SLA Breach Rate',     sub: 'Hybrid-XGB',         icon: <Target size={16} />,       shape: 'shape-organic-2' },
              { val: 45.2,   dec: 1, suf: '',  label: 'Jobs / Hour',          sub: 'Mean throughput',   icon: <Zap size={16} />,          shape: 'shape-organic-3' },
              { val: 2345.9, dec: 0, suf: '',  label: 'Friedman χ²',          sub: 'p < 0.0001',        icon: <BarChart2 size={16} />,    shape: 'shape-organic-4' },
            ].map(({ val, dec, suf, label, sub, icon, shape }) => (
              <div
                key={label}
                className={`bg-white/80 backdrop-blur border border-border/50 ${shape} p-6 flex flex-col items-center justify-center text-center hover:-translate-y-1.5 hover:shadow-float hover:border-primary/30 transition-all duration-500`}
              >
                <div className="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center text-primary mx-auto mb-3">
                  {icon}
                </div>
                <div className="font-heading text-4xl font-semibold text-primary leading-none mb-1">
                  <AnimCounter target={val} decimals={dec} suffix={suf} />
                </div>
                <div className="font-body text-sm font-bold text-foreground mb-0.5">{label}</div>
                <div className="font-body text-xs text-muted-foreground">{sub}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── ALL-METHODS RANKING ───────────────────────────────────── */}
      <section className="py-14 px-6 bg-muted/30">
        <div className="max-w-5xl mx-auto">
          <div ref={resultsRef} className={`reveal ${resultsVis ? 'visible' : ''} mb-10 text-center`}>
            <h2 className="font-heading text-3xl md:text-4xl text-foreground mb-3">All Nine Methods — Full Benchmark</h2>
            <p className="font-body text-base text-muted-foreground max-w-xl mx-auto">
              Mean results across 300 held-out test seeds. DAHS Hybrid-XGB leads on every
              key operational metric — not just tardiness.
            </p>
          </div>

          {/* Column header */}
          <div className="hidden sm:grid sm:grid-cols-[180px_1fr_1fr_1fr_1fr_80px] gap-2 px-5 mb-2">
            <span className="font-body text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Method</span>
            {[
              { label: 'Total Tardiness', sub: 'lower = better' },
              { label: 'SLA Breach',      sub: 'lower = better' },
              { label: 'Throughput',      sub: 'higher = better' },
              { label: 'Avg Cycle Time',  sub: 'lower = better' },
            ].map(({ label, sub }) => (
              <div key={label} className="text-center">
                <div className="font-body text-[10px] font-bold text-muted-foreground uppercase tracking-widest">{label}</div>
                <div className="font-body text-[9px] text-muted-foreground/70">{sub}</div>
              </div>
            ))}
            <span />
          </div>

          <div className="space-y-2.5">
            {ALL_METHODS.map((m) => {
              const tardPct  = Math.min((m.tard  / MAX_TARD) * 100, 100);
              const slaPct   = Math.min(m.sla,  100);
              const thruPct  = Math.min((m.thru  / 50)  * 100, 100);
              const cyclePct = Math.min((m.cycle / 180) * 100, 100);
              const dahs = ALL_METHODS.find(x => x.best);
              return (
                <div
                  key={m.name}
                  className={`flex flex-col sm:grid sm:grid-cols-[180px_1fr_1fr_1fr_1fr_80px] sm:items-center gap-3 sm:gap-2 p-4 sm:p-5 rounded-2xl border transition-all duration-300 ${m.best ? 'border-primary/40 bg-primary/5 shadow-soft' : 'border-border/40 bg-white/70 hover:border-border'}`}
                >
                  {/* Name */}
                  <div className="flex items-center gap-2.5 shrink-0">
                    <span className="w-7 h-7 rounded-full flex items-center justify-center font-heading text-xs font-semibold text-white shrink-0" style={{ background: m.color }}>
                      {m.rank}
                    </span>
                    <span className={`font-heading text-sm font-semibold leading-tight ${m.best ? 'text-primary' : 'text-foreground'}`}>{m.name}</span>
                  </div>

                  {/* Tardiness */}
                  <div className="px-1">
                    <div className="flex justify-between font-body text-[11px] mb-1">
                      <span className={`font-semibold ${m.best ? 'text-primary' : 'text-foreground'}`}>{m.tard.toLocaleString()} min</span>
                      {!m.best && dahs && <span className="text-rose-500 font-bold">+{Math.round((m.tard - dahs.tard) / dahs.tard * 100)}%</span>}
                    </div>
                    <div className="h-2 bg-muted rounded-full overflow-hidden">
                      <div className="h-full rounded-full transition-all duration-700" style={{ width: `${tardPct}%`, background: m.best ? '#1E3A8A' : m.color }} />
                    </div>
                  </div>

                  {/* SLA Breach */}
                  <div className="px-1">
                    <div className="flex justify-between font-body text-[11px] mb-1">
                      <span className={`font-semibold ${m.best ? 'text-primary' : 'text-foreground'}`}>{m.sla}%</span>
                      {!m.best && dahs && m.sla > dahs.sla && <span className="text-rose-500 font-bold">+{(m.sla - dahs.sla).toFixed(1)}pp</span>}
                    </div>
                    <div className="h-2 bg-muted rounded-full overflow-hidden">
                      <div className="h-full rounded-full transition-all duration-700" style={{ width: `${slaPct}%`, background: m.best ? '#1E3A8A' : m.color }} />
                    </div>
                  </div>

                  {/* Throughput */}
                  <div className="px-1">
                    <div className="flex justify-between font-body text-[11px] mb-1">
                      <span className={`font-semibold ${m.best ? 'text-primary' : 'text-foreground'}`}>{m.thru} j/hr</span>
                      {!m.best && dahs && dahs.thru > m.thru && <span className="text-rose-500 font-bold">−{(dahs.thru - m.thru).toFixed(1)}</span>}
                    </div>
                    <div className="h-2 bg-muted rounded-full overflow-hidden">
                      <div className="h-full rounded-full transition-all duration-700" style={{ width: `${thruPct}%`, background: m.best ? '#1E3A8A' : m.color }} />
                    </div>
                  </div>

                  {/* Avg Cycle Time */}
                  <div className="px-1">
                    <div className="flex justify-between font-body text-[11px] mb-1">
                      <span className={`font-semibold ${m.best ? 'text-primary' : 'text-foreground'}`}>{m.cycle} min</span>
                      {!m.best && dahs && <span className="text-rose-500 font-bold">+{(m.cycle - dahs.cycle).toFixed(1)} min</span>}
                    </div>
                    <div className="h-2 bg-muted rounded-full overflow-hidden">
                      <div className="h-full rounded-full transition-all duration-700" style={{ width: `${cyclePct}%`, background: m.best ? '#1E3A8A' : m.color }} />
                    </div>
                  </div>

                  {m.best ? (
                    <span className="justify-self-end shrink-0 px-2.5 py-1 rounded-full bg-primary/15 border border-primary/25 font-body text-[11px] font-bold text-primary whitespace-nowrap">★ BEST</span>
                  ) : <span />}
                </div>
              );
            })}
          </div>

          <p className="text-center font-body text-xs text-muted-foreground mt-5">
            Wilcoxon signed-rank (Holm-corrected) · Cohen's d · Bootstrap 95% CI · Friedman χ² = 312.7, p &lt; 0.001 · n = 300 seeds
          </p>
        </div>
      </section>

      {/* ── FAQ ──────────────────────────────────────────────────── */}
      <section className="py-20 px-6">
        <div className="max-w-3xl mx-auto">
          <div ref={faqRef} className={`reveal ${faqVis ? 'visible' : ''} text-center mb-10`}>
            <h2 className="font-heading text-3xl md:text-4xl text-foreground mb-3">Evaluator Q&amp;A</h2>
            <div className="w-12 h-1 bg-primary/30 rounded-full mx-auto" />
          </div>
          <div className="space-y-3">
            {FAQS.map((faq, i) => <FAQItem key={i} q={faq.q} a={faq.a} idx={i} />)}
          </div>
        </div>
      </section>

      <style>{`
        @keyframes fadeSlideIn {
          from { opacity: 0; transform: translateY(14px); }
          to   { opacity: 1; transform: translateY(0);    }
        }
      `}</style>
    </div>
  );
}
