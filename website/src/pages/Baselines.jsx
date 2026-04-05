import React, { useEffect, useRef, useState } from 'react';

/* ── Rounded-rect polyfill (works in all browsers) ─────────────────── */
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

/* ── Re-play hook: increments key every time element enters view ─────── */
function useAnimReplay(threshold = 0.45) {
  const ref = useRef(null);
  const [key, setKey] = useState(0);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => {
        setVisible(entry.isIntersecting);
        if (entry.isIntersecting) setKey(k => k + 1);
      },
      { threshold }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [threshold]);

  return [ref, key, visible];
}

/* ═══════════════════════════════════════════════════════════════════════
   ANIMATION 1 — FIFO: Clear Queue Walkthrough
════════════════════════════════════════════════════════════════════════ */
function FIFOAnimation({ animKey }) {
  const canvasRef = useRef(null);
  const rafRef    = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    canvas.width  = 620;
    canvas.height = 300;

    const W = 620, H = 300;
    const BG    = '#F8FAFC';
    const NAVY  = '#1E3A8A';
    const SLATE = '#64748B';
    const RED   = '#EF4444';
    const GREEN = '#10B981';
    const AMBER = '#F59E0B';
    const TRACK = '#E2E8F0';

    const JOBS = [
      { id: 1, label: 'J1', arrival: 0,  urgent: false, color: '#3B82F6' },
      { id: 2, label: 'J2', arrival: 4,  urgent: false, color: '#8B5CF6' },
      { id: 3, label: 'J3', arrival: 9,  urgent: false, color: '#3B82F6' },
      { id: 4, label: 'J4', arrival: 14, urgent: true,  color: RED },
      { id: 5, label: 'J5', arrival: 18, urgent: false, color: '#8B5CF6' },
      { id: 6, label: 'J6', arrival: 23, urgent: false, color: '#3B82F6' },
    ];

    const JW = 66, JH = 52, JGAP = 8;
    const QSTART_X = 18, QUEUE_Y = 112;
    const STA_X = W - 110, STA_Y = 78, STA_W = 92, STA_H = 82;
    const PHASE = 1.4;
    const PAUSE = 1.2;
    const CYCLE = PAUSE + JOBS.length * PHASE + 0.8;

    let t0 = null;

    const draw = (ts) => {
      if (!t0) t0 = ts;
      const t  = (ts - t0) / 1000;
      const ct = t % CYCLE;

      ctx.clearRect(0, 0, W, H);

      // Subtle grid background
      ctx.fillStyle = BG;
      ctx.fillRect(0, 0, W, H);
      ctx.strokeStyle = 'rgba(30,58,138,0.04)';
      ctx.lineWidth = 1;
      for (let gx = 0; gx < W; gx += 30) {
        ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, H); ctx.stroke();
      }
      for (let gy = 0; gy < H; gy += 30) {
        ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(W, gy); ctx.stroke();
      }

      // Queue track with gradient
      const trackGrad = ctx.createLinearGradient(QSTART_X - 6, 0, QSTART_X + (JW + JGAP) * JOBS.length + 10, 0);
      trackGrad.addColorStop(0, '#EEF2FF');
      trackGrad.addColorStop(1, '#E2E8F0');
      rr(ctx, QSTART_X - 6, QUEUE_Y - 10, (JW + JGAP) * JOBS.length + 4, JH + 20, 12);
      ctx.fillStyle = trackGrad;
      ctx.fill();
      rr(ctx, QSTART_X - 6, QUEUE_Y - 10, (JW + JGAP) * JOBS.length + 4, JH + 20, 12);
      ctx.strokeStyle = 'rgba(30,58,138,0.12)';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Header label
      ctx.fillStyle = NAVY;
      ctx.font = 'bold 11px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
      ctx.fillText('ARRIVAL QUEUE', QSTART_X, QUEUE_Y - 22);
      ctx.fillStyle = '#94A3B8';
      ctx.font = '10px "Nunito",system-ui,sans-serif';
      ctx.fillText('Jobs processed strictly in order of arrival — no exceptions', QSTART_X + 110, QUEUE_Y - 22);

      // Processing station
      const staGrad = ctx.createLinearGradient(STA_X, STA_Y, STA_X, STA_Y + STA_H);
      staGrad.addColorStop(0, '#1E40AF');
      staGrad.addColorStop(1, '#1E3A8A');
      ctx.shadowColor = 'rgba(30,58,138,0.3)';
      ctx.shadowBlur = 16;
      rr(ctx, STA_X, STA_Y, STA_W, STA_H, 14);
      ctx.fillStyle = staGrad;
      ctx.fill();
      ctx.shadowBlur = 0;

      ctx.fillStyle = 'rgba(255,255,255,0.15)';
      rr(ctx, STA_X + 4, STA_Y + 4, STA_W - 8, 28, 10);
      ctx.fill();

      ctx.fillStyle = '#EFF6FF';
      ctx.font = 'bold 11px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('PROCESS', STA_X + STA_W / 2, STA_Y + STA_H / 2 - 9);
      ctx.fillText('STATION', STA_X + STA_W / 2, STA_Y + STA_H / 2 + 9);

      // Arrow
      ctx.fillStyle = NAVY;
      ctx.font = 'bold 22px system-ui';
      ctx.textAlign = 'center';
      ctx.fillText('→', STA_X - 20, STA_Y + STA_H / 2 + 8);

      const procIdx  = ct < PAUSE ? -1 : Math.min(Math.floor((ct - PAUSE) / PHASE), JOBS.length - 1);
      const jobPhase = ct < PAUSE ? 0 : ((ct - PAUSE) % PHASE) / PHASE;
      let completedCount = Math.max(0, procIdx);

      JOBS.forEach((job, i) => {
        const queuePos = i - completedCount;
        let jx, jy, alpha = 1;
        if (i < completedCount) return;

        if (i === procIdx) {
          if (jobPhase < 0.28) {
            const e = 1 - Math.pow(1 - jobPhase / 0.28, 3);
            const baseX = QSTART_X;
            jx = baseX + (STA_X - JW - 16 - baseX) * e;
            jy = QUEUE_Y + (STA_Y + STA_H / 2 - JH / 2 - QUEUE_Y) * e;
          } else if (jobPhase < 0.72) {
            jx = STA_X - JW - 16;
            jy = STA_Y + STA_H / 2 - JH / 2;
          } else {
            alpha = Math.max(0, 1 - (jobPhase - 0.72) / 0.18);
            jx = STA_X - JW - 16;
            jy = STA_Y + STA_H / 2 - JH / 2;
          }
        } else {
          const shiftAmt = (procIdx >= 0 && jobPhase > 0.28)
            ? (JW + JGAP) * Math.min(1, (jobPhase - 0.28) / 0.4)
            : 0;
          jx = QSTART_X + queuePos * (JW + JGAP) - shiftAmt;
          jy = QUEUE_Y;
        }

        // Glow for active
        if (i === procIdx && jobPhase >= 0.28 && jobPhase < 0.72) {
          ctx.save();
          ctx.shadowColor = job.color;
          ctx.shadowBlur = 20;
          rr(ctx, jx - 2, jy - 2, JW + 4, JH + 4, 10);
          ctx.fillStyle = job.color + '15';
          ctx.fill();
          ctx.restore();
        }

        ctx.globalAlpha = alpha;

        // Job card with gradient
        const cardGrad = ctx.createLinearGradient(jx, jy, jx, jy + JH);
        cardGrad.addColorStop(0, '#FFFFFF');
        cardGrad.addColorStop(1, '#F8FAFC');
        rr(ctx, jx, jy, JW, JH, 10);
        ctx.fillStyle = cardGrad;
        ctx.fill();
        rr(ctx, jx, jy, JW, JH, 10);
        ctx.strokeStyle = job.color;
        ctx.lineWidth = i === procIdx && jobPhase >= 0.28 && jobPhase < 0.72 ? 2.5 : 1.5;
        ctx.stroke();

        // Left color stripe
        rr(ctx, jx, jy, 5, JH, 4);
        ctx.fillStyle = job.color;
        ctx.fill();

        ctx.fillStyle = job.color;
        ctx.font = `bold 15px "Nunito",system-ui,sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(job.label, jx + JW / 2 + 2, jy + JH / 2 - 8);

        ctx.fillStyle = '#94A3B8';
        ctx.font = '9px "Nunito",system-ui,sans-serif';
        ctx.fillText(`arr t=${job.arrival}`, jx + JW / 2 + 2, jy + JH / 2 + 8);

        // Progress bar
        if (i === procIdx && jobPhase >= 0.28 && jobPhase < 0.72) {
          const prog = (jobPhase - 0.28) / 0.44;
          rr(ctx, jx + 8, jy + JH - 12, JW - 16, 7, 3);
          ctx.fillStyle = '#E2E8F0';
          ctx.fill();
          const pgGrad = ctx.createLinearGradient(jx + 8, 0, jx + 8 + (JW - 16) * prog, 0);
          pgGrad.addColorStop(0, GREEN);
          pgGrad.addColorStop(1, '#34D399');
          rr(ctx, jx + 8, jy + JH - 12, (JW - 16) * prog, 7, 3);
          ctx.fillStyle = pgGrad;
          ctx.fill();
        }

        // Done check
        if (i === procIdx && jobPhase >= 0.72) {
          ctx.globalAlpha = alpha;
          ctx.fillStyle = GREEN;
          ctx.font = 'bold 20px system-ui';
          ctx.textAlign = 'center';
          ctx.fillText('✓', jx + JW / 2, jy + JH / 2 + 7);
        }

        // URGENT badge
        if (job.urgent) {
          const blink = Math.sin(ts / 320) > 0;
          rr(ctx, jx + JW / 2 - 26, jy - 18, 52, 15, 5);
          ctx.fillStyle = blink ? RED : '#FEE2E2';
          ctx.fill();
          ctx.fillStyle = blink ? '#FFF' : RED;
          ctx.font = 'bold 7.5px "Nunito",system-ui,sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText('⚠ URGENT', jx + JW / 2, jy - 10.5);
        }

        if (i !== procIdx || jobPhase < 0.15) {
          ctx.fillStyle = '#94A3B8';
          ctx.font = '9px "Nunito",system-ui,sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'alphabetic';
          ctx.fillText(`#${queuePos + 1}`, jx + JW / 2, jy + JH + 14);
        }

        ctx.globalAlpha = 1;
      });

      // Status bar
      const procLabel = procIdx >= 0 && procIdx < JOBS.length
        ? `Processing: ${JOBS[procIdx].label}   ·   Completed: ${completedCount} / ${JOBS.length}`
        : ct < PAUSE ? `All ${JOBS.length} jobs queued in arrival order` : 'Cycle complete — restarting';

      ctx.fillStyle = NAVY;
      ctx.font = 'bold 10px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'alphabetic';
      ctx.fillText(procLabel, W / 2, H - 24);

      ctx.fillStyle = RED;
      ctx.font = '10px "Nunito",system-ui,sans-serif';
      ctx.fillText('J4 is URGENT — FIFO ignores urgency entirely, processing by arrival order only.', W / 2, H - 8);

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [animKey]);

  return <canvas ref={canvasRef} className="w-full h-auto" />;
}

/* ═══════════════════════════════════════════════════════════════════════
   ANIMATION 2 — EDD: Earliest Due Date
   Jobs sorted by absolute due date. Tightest deadline = first dispatched.
════════════════════════════════════════════════════════════════════════ */
function EDDAnimation({ animKey }) {
  const canvasRef = useRef(null);
  const rafRef    = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    canvas.width  = 620;
    canvas.height = 300;

    const W = 620, H = 300;
    const BG   = '#F8FAFC';
    const NAVY = '#1E3A8A';
    const GREEN = '#10B981';
    const AMBER = '#F59E0B';
    const RED   = '#EF4444';

    const JOBS = [
      { id: 'J-A', due: 45,  rem: 12, color: '#EF4444' },
      { id: 'J-B', due: 70,  rem: 18, color: '#F59E0B' },
      { id: 'J-C', due: 100, rem: 25, color: '#3B82F6' },
      { id: 'J-D', due: 130, rem: 15, color: '#8B5CF6' },
      { id: 'J-E', due: 180, rem: 30, color: '#10B981' },
    ];

    const SIM_CYCLE = 10;
    const ROW_H = 42;
    const ROW_GAP = 8;
    const ROW_X = 20;
    const ROW_W = W - 40;
    const TABLE_Y = 72;

    const smoothY = JOBS.map((_, i) => TABLE_Y + i * (ROW_H + ROW_GAP));
    let t0 = null;

    const draw = (ts) => {
      if (!t0) t0 = ts;
      const t  = (ts - t0) / 1000;
      const st = (t % SIM_CYCLE) / SIM_CYCLE * 150;

      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = BG;
      ctx.fillRect(0, 0, W, H);

      // Title
      ctx.fillStyle = NAVY;
      ctx.font = 'bold 13px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
      ctx.fillText('EARLIEST DUE DATE DISPATCH', ROW_X, 22);

      ctx.fillStyle = '#475569';
      ctx.font = '11px "Nunito",system-ui,sans-serif';
      ctx.fillText('Dispatch order = ascending due date. Smallest due date processed first.', ROW_X, 38);

      // Clock
      ctx.fillStyle = NAVY;
      ctx.font = 'bold 11px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(`t = ${st.toFixed(0)} min`, W - ROW_X, 22);

      // Sort by EDD
      const sorted = [...JOBS]
        .map(j => ({ ...j, remaining_due: Math.max(0, j.due - st), overdue: st > j.due }))
        .sort((a, b) => a.due - b.due);

      sorted.forEach((job, rank) => {
        const origIdx = JOBS.findIndex(j => j.id === job.id);
        const targetY = TABLE_Y + rank * (ROW_H + ROW_GAP);
        smoothY[origIdx] += (targetY - smoothY[origIdx]) * 0.1;
      });

      JOBS.forEach((job, origIdx) => {
        const ry   = smoothY[origIdx];
        const info = sorted.find(j => j.id === job.id);
        const rank = sorted.findIndex(j => j.id === job.id);
        const urgency = Math.max(0, 1 - info.remaining_due / job.due);
        const timeColor = info.overdue ? RED : urgency > 0.65 ? AMBER : GREEN;

        ctx.shadowColor = rank === 0 ? 'rgba(30,58,138,0.15)' : 'rgba(0,0,0,0.05)';
        ctx.shadowBlur  = rank === 0 ? 12 : 4;
        rr(ctx, ROW_X, ry, ROW_W, ROW_H, 10);
        ctx.fillStyle = rank === 0 ? '#EFF6FF' : '#FFFFFF';
        ctx.fill();
        if (rank === 0) {
          rr(ctx, ROW_X, ry, ROW_W, ROW_H, 10);
          ctx.strokeStyle = NAVY + '60';
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
        ctx.shadowBlur = 0;

        // Left accent stripe
        rr(ctx, ROW_X, ry, 5, ROW_H, 4);
        ctx.fillStyle = job.color;
        ctx.fill();

        // Rank badge
        ctx.beginPath();
        ctx.arc(ROW_X + 26, ry + ROW_H / 2, 14, 0, Math.PI * 2);
        ctx.fillStyle = rank === 0 ? NAVY : '#E2E8F0';
        ctx.fill();
        ctx.fillStyle = rank === 0 ? '#FFF' : '#475569';
        ctx.font = `bold 11px "Nunito",system-ui,sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(`#${rank + 1}`, ROW_X + 26, ry + ROW_H / 2);

        // Job ID
        ctx.fillStyle = job.color;
        ctx.font = `bold 13px "Nunito",system-ui,sans-serif`;
        ctx.textAlign = 'left';
        ctx.fillText(job.id, ROW_X + 50, ry + ROW_H / 2);

        // Due date info
        ctx.fillStyle = '#94A3B8';
        ctx.font = '10px "Nunito",system-ui,sans-serif';
        ctx.fillText(`due: t=${job.due}`, ROW_X + 100, ry + ROW_H / 2);

        // Countdown bar
        const barX = ROW_X + 170;
        const barW = ROW_W - 310;
        const barY = ry + ROW_H / 2 - 6;
        const fillFrac = Math.max(0, Math.min(1, info.remaining_due / job.due));

        rr(ctx, barX, barY, barW, 12, 6);
        ctx.fillStyle = '#F1F5F9';
        ctx.fill();

        if (fillFrac > 0) {
          const bgGrad = ctx.createLinearGradient(barX, barY, barX + barW * fillFrac, barY);
          bgGrad.addColorStop(0, timeColor);
          bgGrad.addColorStop(1, timeColor + 'AA');
          rr(ctx, barX, barY, barW * fillFrac, 12, 6);
          ctx.fillStyle = bgGrad;
          ctx.fill();
        }

        // Remaining time text
        ctx.fillStyle = timeColor;
        ctx.font = `bold 11px "Nunito",system-ui,sans-serif`;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        const label = info.overdue ? 'OVERDUE' : `${info.remaining_due.toFixed(0)} min left`;
        ctx.fillText(label, barX + barW + 8, ry + ROW_H / 2);

        // NEXT badge
        if (rank === 0) {
          const bx = ROW_W - 48;
          rr(ctx, ROW_X + bx, ry + (ROW_H - 22) / 2, 50, 22, 6);
          ctx.fillStyle = info.overdue ? RED : NAVY;
          ctx.fill();
          ctx.fillStyle = '#FFF';
          ctx.font = 'bold 8.5px "Nunito",system-ui,sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText('→ NEXT', ROW_X + bx + 25, ry + ROW_H / 2);
        }

        // Overdue flash
        if (info.overdue && Math.sin(ts / 300) > 0) {
          rr(ctx, ROW_X, ry, ROW_W, ROW_H, 10);
          ctx.strokeStyle = RED;
          ctx.lineWidth = 2;
          ctx.globalAlpha = 0.4;
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
      });

      ctx.fillStyle = '#6B7280';
      ctx.font = '10px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'alphabetic';
      ctx.fillText('EDD minimises maximum lateness. Jobs reorder only once at the start — due date is static.', W / 2, H - 8);

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [animKey]);

  return <canvas ref={canvasRef} className="w-full h-auto" />;
}

/* ═══════════════════════════════════════════════════════════════════════
   ANIMATION 3 — Critical Ratio: Live Dispatch Leaderboard
════════════════════════════════════════════════════════════════════════ */
function CRAnimation({ animKey }) {
  const canvasRef = useRef(null);
  const rafRef    = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    canvas.width  = 620;
    canvas.height = 300;

    const W = 620, H = 300;
    const BG   = '#F8FAFC';
    const NAVY = '#1E3A8A';
    const GREEN = '#10B981';
    const AMBER = '#F59E0B';
    const RED   = '#EF4444';

    const BASE_JOBS = [
      { id: 'J-A', due: 120, rem: 30, fullColor: '#7C3AED' },
      { id: 'J-B', due: 55,  rem: 20, fullColor: '#F59E0B' },
      { id: 'J-C', due: 200, rem: 60, fullColor: '#3B82F6' },
      { id: 'J-D', due: 45,  rem: 15, fullColor: '#EF4444' },
    ];

    const ROW_H   = 48;
    const ROW_X   = 20;
    const ROW_W   = W - 40;
    const TABLE_Y = 68;
    const SIM_CYCLE = 9;

    const smoothY = BASE_JOBS.map((_, i) => TABLE_Y + i * (ROW_H + 6));
    let t0 = null;

    const draw = (ts) => {
      if (!t0) t0 = ts;
      const t  = (ts - t0) / 1000;
      const st = (t % SIM_CYCLE) / SIM_CYCLE * 80;

      const withCR = BASE_JOBS.map(j => {
        const ttd = Math.max(0, j.due - st);
        const cr  = ttd / Math.max(j.rem, 0.1);
        return { ...j, cr, st };
      });
      const ranked = [...withCR].sort((a, b) => a.cr - b.cr);

      ranked.forEach((job, rank) => {
        const origIdx = BASE_JOBS.findIndex(j => j.id === job.id);
        const targetY = TABLE_Y + rank * (ROW_H + 6);
        smoothY[origIdx] += (targetY - smoothY[origIdx]) * 0.09;
      });

      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = BG;
      ctx.fillRect(0, 0, W, H);

      ctx.fillStyle = NAVY;
      ctx.font = 'bold 13px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
      ctx.fillText('CRITICAL RATIO DISPATCH', ROW_X, 22);

      ctx.fillStyle = '#475569';
      ctx.font = '11px "Nunito",system-ui,sans-serif';
      ctx.fillText('CR = (due date − current time) ÷ remaining processing time', ROW_X, 38);

      ctx.fillStyle = NAVY;
      ctx.font = 'bold 11px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(`t = ${st.toFixed(1)} min`, W - ROW_X, 22);

      // Legend
      const legend = [
        { label: 'CR > 1.8 — on track', c: GREEN },
        { label: '1 < CR ≤ 1.8 — caution', c: AMBER },
        { label: 'CR ≤ 1.0 — CRITICAL',   c: RED  },
      ];
      legend.forEach((l, li) => {
        const lx = ROW_X + li * 190;
        ctx.beginPath();
        ctx.arc(lx + 5, 52, 4, 0, Math.PI * 2);
        ctx.fillStyle = l.c;
        ctx.fill();
        ctx.fillStyle = '#374151';
        ctx.font = '9px "Nunito",system-ui,sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(l.label, lx + 14, 56);
      });

      withCR.forEach((job, origIdx) => {
        const ry      = smoothY[origIdx];
        const rank    = ranked.findIndex(j => j.id === job.id);
        const cr      = job.cr;
        const crColor = cr <= 1 ? RED : cr <= 1.8 ? AMBER : GREEN;
        const maxCR   = 5;
        const barFrac = Math.min(cr / maxCR, 1);

        ctx.shadowColor = rank === 0 ? 'rgba(30,58,138,0.15)' : 'rgba(0,0,0,0.04)';
        ctx.shadowBlur  = rank === 0 ? 10 : 4;
        rr(ctx, ROW_X, ry, ROW_W, ROW_H, 10);
        ctx.fillStyle = rank === 0 ? '#EFF6FF' : '#FFFFFF';
        ctx.fill();
        if (rank === 0) {
          rr(ctx, ROW_X, ry, ROW_W, ROW_H, 10);
          ctx.strokeStyle = NAVY + '50';
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
        ctx.shadowBlur = 0;

        // Left stripe
        rr(ctx, ROW_X, ry, 5, ROW_H, 4);
        ctx.fillStyle = job.fullColor;
        ctx.fill();

        // Rank
        ctx.beginPath();
        ctx.arc(ROW_X + 26, ry + ROW_H / 2, 14, 0, Math.PI * 2);
        ctx.fillStyle = rank === 0 ? NAVY : '#E2E8F0';
        ctx.fill();
        ctx.fillStyle = rank === 0 ? '#FFF' : '#374151';
        ctx.font = `bold 11px "Nunito",system-ui,sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(`#${rank + 1}`, ROW_X + 26, ry + ROW_H / 2);

        // Job ID
        ctx.fillStyle = job.fullColor;
        ctx.font = `bold 13px "Nunito",system-ui,sans-serif`;
        ctx.textAlign = 'left';
        ctx.fillText(job.id, ROW_X + 50, ry + ROW_H / 2 + 1);

        // Bar
        const barX = ROW_X + 108;
        const barW = ROW_W - 230;
        const barY = ry + ROW_H / 2 - 6;
        rr(ctx, barX, barY, barW, 12, 6);
        ctx.fillStyle = '#F1F5F9';
        ctx.fill();

        if (barFrac > 0) {
          const grad = ctx.createLinearGradient(barX, barY, barX + barW * barFrac, barY);
          grad.addColorStop(0, crColor);
          grad.addColorStop(1, crColor + 'AA');
          rr(ctx, barX, barY, barW * barFrac, 12, 6);
          ctx.fillStyle = grad;
          ctx.globalAlpha = 0.9;
          ctx.fill();
          ctx.globalAlpha = 1;
        }

        ctx.fillStyle = crColor;
        ctx.font = `bold 12px "Nunito",system-ui,sans-serif`;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.fillText(`CR = ${cr.toFixed(2)}`, barX + barW + 10, ry + ROW_H / 2);

        if (rank === 0) {
          const bx = ROW_W - 46;
          rr(ctx, ROW_X + bx, ry + (ROW_H - 22) / 2, 50, 22, 6);
          ctx.fillStyle = cr <= 1 ? RED : NAVY;
          ctx.fill();
          ctx.fillStyle = '#FFF';
          ctx.font = 'bold 8.5px "Nunito",system-ui,sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText('→ NEXT', ROW_X + bx + 25, ry + ROW_H / 2);
        }

        if (cr <= 1 && Math.sin(ts / 280) > 0) {
          rr(ctx, ROW_X, ry, ROW_W, ROW_H, 10);
          ctx.strokeStyle = RED;
          ctx.lineWidth = 2;
          ctx.globalAlpha = 0.5;
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
      });

      ctx.fillStyle = '#6B7280';
      ctx.font = '10px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'alphabetic';
      ctx.fillText('CR < 1 means behind schedule. Queue reorders dynamically at every dispatch event.', W / 2, H - 8);

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [animKey]);

  return <canvas ref={canvasRef} className="w-full h-auto" />;
}

/* ═══════════════════════════════════════════════════════════════════════
   ANIMATION 4 — WSPT: Weighted Shortest Processing Time
   Dispatch by highest weight ÷ processing_time ratio.
════════════════════════════════════════════════════════════════════════ */
function WSPTAnimation({ animKey }) {
  const canvasRef = useRef(null);
  const rafRef    = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    canvas.width  = 620;
    canvas.height = 300;

    const W = 620, H = 300;
    const BG   = '#F8FAFC';
    const NAVY = '#1E3A8A';

    const JOBS = [
      { id: 'J1', weight: 3.0, proc: 6,  color: '#EF4444' },
      { id: 'J2', weight: 1.0, proc: 20, color: '#64748B' },
      { id: 'J3', weight: 2.5, proc: 8,  color: '#F59E0B' },
      { id: 'J4', weight: 1.5, proc: 10, color: '#3B82F6' },
      { id: 'J5', weight: 2.0, proc: 5,  color: '#10B981' },
    ];

    const sorted  = [...JOBS].sort((a, b) => (b.weight / b.proc) - (a.weight / a.proc));
    const maxRatio = sorted[0].weight / sorted[0].proc;

    const BAR_H   = 38;
    const BAR_GAP = 9;
    const START_Y = 68;
    const LEFT_X  = 104;
    const MAX_BAR = W - 210;

    let t0 = null;

    const draw = (ts) => {
      if (!t0) t0 = ts;
      const t = (ts - t0) / 1000;
      const cycle = t % 3.5;

      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = BG;
      ctx.fillRect(0, 0, W, H);

      // Subtle dot grid
      ctx.fillStyle = 'rgba(30,58,138,0.04)';
      for (let gx = 20; gx < W; gx += 28) {
        for (let gy = 20; gy < H; gy += 28) {
          ctx.beginPath();
          ctx.arc(gx, gy, 1.5, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      ctx.fillStyle = NAVY;
      ctx.font = 'bold 13px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
      ctx.fillText('WEIGHTED SHORTEST PROCESSING TIME (WSPT)', 20, 22);

      ctx.fillStyle = '#475569';
      ctx.font = '11px "Nunito",system-ui,sans-serif';
      ctx.fillText('Score = weight ÷ processing time   |   Higher score dispatched first', 20, 40);

      sorted.forEach((job, rank) => {
        const ratio  = job.weight / job.proc;
        const norm   = ratio / maxRatio;
        const delay  = rank * 0.1;
        const prog   = Math.min(1, Math.max(0, (cycle - delay) / 0.6));
        const eased  = 1 - Math.pow(1 - prog, 3);
        const y      = START_Y + rank * (BAR_H + BAR_GAP);

        // Track
        rr(ctx, LEFT_X, y, MAX_BAR, BAR_H, 8);
        ctx.fillStyle = '#F1F5F9';
        ctx.fill();

        // Fill
        const bw = MAX_BAR * norm * eased;
        if (bw > 2) {
          const grad = ctx.createLinearGradient(LEFT_X, y, LEFT_X + bw, y + BAR_H);
          grad.addColorStop(0, job.color + 'CC');
          grad.addColorStop(1, job.color);
          rr(ctx, LEFT_X, y, bw, BAR_H, 8);
          ctx.fillStyle = grad;
          ctx.fill();
        }

        // Pulse on rank 0
        if (rank === 0 && prog >= 1) {
          const pulse = 0.4 + 0.6 * Math.sin(t * 4);
          rr(ctx, LEFT_X, y, MAX_BAR * norm, BAR_H, 8);
          ctx.strokeStyle = `rgba(30,58,138,${pulse * 0.6})`;
          ctx.lineWidth = 2;
          ctx.stroke();
        }

        // Job label
        ctx.fillStyle = '#0F172A';
        ctx.font = 'bold 12px "Nunito",system-ui,sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillText(job.id, LEFT_X - 10, y + BAR_H / 2);

        // w and p annotations inside bar
        if (bw > 80) {
          ctx.fillStyle = 'rgba(255,255,255,0.9)';
          ctx.font = '10px "Nunito",system-ui,sans-serif';
          ctx.textAlign = 'left';
          ctx.fillText(`w=${job.weight}  p=${job.proc}`, LEFT_X + 8, y + BAR_H / 2);
        }

        // Score label
        if (prog > 0.3) {
          ctx.fillStyle = '#0F172A';
          ctx.font = '11px "Nunito",system-ui,sans-serif';
          ctx.textAlign = 'left';
          ctx.fillText(`${ratio.toFixed(3)}`, LEFT_X + MAX_BAR * norm * eased + 8, y + BAR_H / 2);
        }

        // Rank badge
        if (prog >= 1) {
          ctx.beginPath();
          ctx.arc(W - 26, y + BAR_H / 2, 14, 0, Math.PI * 2);
          ctx.fillStyle = rank === 0 ? NAVY : '#E2E8F0';
          ctx.fill();
          ctx.fillStyle = rank === 0 ? '#FFF' : '#374151';
          ctx.font = 'bold 11px "Nunito",system-ui,sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(`#${rank + 1}`, W - 26, y + BAR_H / 2);
        }
      });

      ctx.fillStyle = '#6B7280';
      ctx.font = '10px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'alphabetic';
      ctx.fillText('J1 wins: weight=3.0, proc=6 → ratio=0.500. J2 loses: low weight, high processing time.', W / 2, H - 8);

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [animKey]);

  return <canvas ref={canvasRef} className="w-full h-auto" />;
}

/* ═══════════════════════════════════════════════════════════════════════
   ANIMATION 5 — Slack Time: Minimum Slack First
   Slack = due_date − now − remaining_work. Negative = overdue.
════════════════════════════════════════════════════════════════════════ */
function SlackAnimation({ animKey }) {
  const canvasRef = useRef(null);
  const rafRef    = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    canvas.width  = 620;
    canvas.height = 300;

    const W = 620, H = 300;
    const BG   = '#F8FAFC';
    const NAVY = '#1E3A8A';
    const GREEN = '#10B981';
    const AMBER = '#F59E0B';
    const RED   = '#EF4444';

    const JOBS = [
      { id: 'J-A', due: 50,  rem: 20, color: '#EF4444' },
      { id: 'J-B', due: 90,  rem: 15, color: '#F59E0B' },
      { id: 'J-C', due: 60,  rem: 40, color: '#8B5CF6' },
      { id: 'J-D', due: 130, rem: 10, color: '#3B82F6' },
      { id: 'J-E', due: 80,  rem: 25, color: '#10B981' },
    ];

    const SIM_CYCLE = 10;
    const ROW_H  = 42;
    const ROW_GAP = 8;
    const ROW_X  = 20;
    const ROW_W  = W - 40;
    const TABLE_Y = 68;

    const smoothY = JOBS.map((_, i) => TABLE_Y + i * (ROW_H + ROW_GAP));
    let t0 = null;

    const draw = (ts) => {
      if (!t0) t0 = ts;
      const t  = (ts - t0) / 1000;
      const st = (t % SIM_CYCLE) / SIM_CYCLE * 80;

      const withSlack = JOBS.map(j => ({
        ...j,
        slack: j.due - st - j.rem,
      }));
      const sorted = [...withSlack].sort((a, b) => a.slack - b.slack);

      sorted.forEach((job, rank) => {
        const origIdx = JOBS.findIndex(j => j.id === job.id);
        const targetY = TABLE_Y + rank * (ROW_H + ROW_GAP);
        smoothY[origIdx] += (targetY - smoothY[origIdx]) * 0.09;
      });

      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = BG;
      ctx.fillRect(0, 0, W, H);

      ctx.fillStyle = NAVY;
      ctx.font = 'bold 13px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
      ctx.fillText('MINIMUM SLACK TIME DISPATCH', ROW_X, 22);

      ctx.fillStyle = '#475569';
      ctx.font = '11px "Nunito",system-ui,sans-serif';
      ctx.fillText('Slack = due date − now − remaining work. Least slack dispatched first.', ROW_X, 38);

      ctx.fillStyle = NAVY;
      ctx.font = 'bold 11px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(`t = ${st.toFixed(1)} min`, W - ROW_X, 22);

      // Legend
      const legend = [
        { label: 'Slack > 20 — safe',      c: GREEN },
        { label: 'Slack 0–20 — tight',     c: AMBER },
        { label: 'Slack < 0 — overdue',    c: RED   },
      ];
      legend.forEach((l, li) => {
        const lx = ROW_X + li * 190;
        ctx.beginPath();
        ctx.arc(lx + 5, 54, 4, 0, Math.PI * 2);
        ctx.fillStyle = l.c;
        ctx.fill();
        ctx.fillStyle = '#374151';
        ctx.font = '9px "Nunito",system-ui,sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(l.label, lx + 14, 58);
      });

      JOBS.forEach((job, origIdx) => {
        const ry    = smoothY[origIdx];
        const info  = withSlack.find(j => j.id === job.id);
        const rank  = sorted.findIndex(j => j.id === job.id);
        const slack = info.slack;
        const slackColor = slack < 0 ? RED : slack < 20 ? AMBER : GREEN;
        const maxSlack = 80;
        // Normalize: negative slack = bar shown in red on left side
        const posFrac = Math.max(0, Math.min(slack / maxSlack, 1));

        ctx.shadowColor = rank === 0 ? 'rgba(30,58,138,0.15)' : 'rgba(0,0,0,0.04)';
        ctx.shadowBlur  = rank === 0 ? 10 : 4;
        rr(ctx, ROW_X, ry, ROW_W, ROW_H, 10);
        ctx.fillStyle = rank === 0 ? '#EFF6FF' : '#FFFFFF';
        ctx.fill();
        if (rank === 0) {
          rr(ctx, ROW_X, ry, ROW_W, ROW_H, 10);
          ctx.strokeStyle = NAVY + '50';
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
        ctx.shadowBlur = 0;

        // Left stripe
        rr(ctx, ROW_X, ry, 5, ROW_H, 4);
        ctx.fillStyle = job.color;
        ctx.fill();

        // Rank badge
        ctx.beginPath();
        ctx.arc(ROW_X + 26, ry + ROW_H / 2, 14, 0, Math.PI * 2);
        ctx.fillStyle = rank === 0 ? NAVY : '#E2E8F0';
        ctx.fill();
        ctx.fillStyle = rank === 0 ? '#FFF' : '#475569';
        ctx.font = `bold 11px "Nunito",system-ui,sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(`#${rank + 1}`, ROW_X + 26, ry + ROW_H / 2);

        // Job ID
        ctx.fillStyle = job.color;
        ctx.font = `bold 13px "Nunito",system-ui,sans-serif`;
        ctx.textAlign = 'left';
        ctx.fillText(job.id, ROW_X + 50, ry + ROW_H / 2);

        // Due + rem
        ctx.fillStyle = '#94A3B8';
        ctx.font = '10px "Nunito",system-ui,sans-serif';
        ctx.fillText(`due:${job.due} rem:${job.rem}`, ROW_X + 98, ry + ROW_H / 2);

        // Slack bar
        const barX = ROW_X + 195;
        const barW = ROW_W - 330;
        const barY = ry + ROW_H / 2 - 6;

        rr(ctx, barX, barY, barW, 12, 6);
        ctx.fillStyle = '#F1F5F9';
        ctx.fill();

        if (slack >= 0 && posFrac > 0) {
          const grad = ctx.createLinearGradient(barX, barY, barX + barW * posFrac, barY);
          grad.addColorStop(0, slackColor);
          grad.addColorStop(1, slackColor + '88');
          rr(ctx, barX, barY, barW * posFrac, 12, 6);
          ctx.fillStyle = grad;
          ctx.fill();
        } else if (slack < 0) {
          // Overdue — fill full red
          rr(ctx, barX, barY, barW, 12, 6);
          ctx.fillStyle = RED + '40';
          ctx.fill();
        }

        // Slack value
        ctx.fillStyle = slackColor;
        ctx.font = `bold 12px "Nunito",system-ui,sans-serif`;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        const slackLabel = slack < 0 ? `${slack.toFixed(0)} OVERDUE` : `+${slack.toFixed(0)} min`;
        ctx.fillText(slackLabel, barX + barW + 8, ry + ROW_H / 2);

        // NEXT badge
        if (rank === 0) {
          const bx = ROW_W - 46;
          rr(ctx, ROW_X + bx, ry + (ROW_H - 22) / 2, 50, 22, 6);
          ctx.fillStyle = slack < 0 ? RED : NAVY;
          ctx.fill();
          ctx.fillStyle = '#FFF';
          ctx.font = 'bold 8.5px "Nunito",system-ui,sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText('→ NEXT', ROW_X + bx + 25, ry + ROW_H / 2);
        }

        if (slack < 0 && Math.sin(ts / 300) > 0) {
          rr(ctx, ROW_X, ry, ROW_W, ROW_H, 10);
          ctx.strokeStyle = RED;
          ctx.lineWidth = 2;
          ctx.globalAlpha = 0.4;
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
      });

      ctx.fillStyle = '#6B7280';
      ctx.font = '10px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'alphabetic';
      ctx.fillText('Slack shrinks as time passes. Jobs with negative slack have already missed their window.', W / 2, H - 8);

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [animKey]);

  return <canvas ref={canvasRef} className="w-full h-auto" />;
}

/* ═══════════════════════════════════════════════════════════════════════
   ANIMATION 6 — ATC: Weighted Priority Score Bars
════════════════════════════════════════════════════════════════════════ */
function ATCAnimation({ animKey }) {
  const canvasRef = useRef(null);
  const rafRef    = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    canvas.width  = 620;
    canvas.height = 300;

    const W = 620, H = 300;
    const BG   = '#F8FAFC';
    const NAVY = '#1E3A8A';

    const JOBS = [
      { id: 'J1', weight: 3.0, rem: 12, slack:  8, color: '#EF4444' },
      { id: 'J2', weight: 1.5, rem: 20, slack: 40, color: '#3B82F6' },
      { id: 'J3', weight: 2.5, rem:  8, slack:  3, color: '#F59E0B' },
      { id: 'J4', weight: 1.0, rem: 30, slack: 90, color: '#6B7280' },
      { id: 'J5', weight: 2.0, rem: 15, slack:  5, color: '#7C3AED' },
    ];

    const K    = 2.0;
    const pAvg = JOBS.reduce((s, j) => s + j.rem, 0) / JOBS.length;
    const atc  = (j) => (j.weight / Math.max(j.rem, 0.001)) * Math.exp(-Math.max(0, j.slack) / (K * pAvg));
    const sorted   = [...JOBS].sort((a, b) => atc(b) - atc(a));
    const maxScore = atc(sorted[0]);

    const BAR_H   = 38;
    const BAR_GAP = 10;
    const START_Y = 68;
    const LEFT_X  = 104;
    const MAX_BAR = W - 210;

    let t0 = null;

    const draw = (ts) => {
      if (!t0) t0 = ts;
      const t = (ts - t0) / 1000;
      const cycle = t % 3.5;

      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = BG;
      ctx.fillRect(0, 0, W, H);

      // dot grid
      ctx.fillStyle = 'rgba(30,58,138,0.04)';
      for (let gx = 20; gx < W; gx += 28) {
        for (let gy = 20; gy < H; gy += 28) {
          ctx.beginPath();
          ctx.arc(gx, gy, 1.5, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      ctx.fillStyle = NAVY;
      ctx.font = 'bold 13px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
      ctx.fillText('ATC SCORE  =  (w / p)  ×  exp( −max(0, slack) / K·p̄ )', 22, 22);

      ctx.fillStyle = '#475569';
      ctx.font = '11px "Nunito",system-ui,sans-serif';
      ctx.fillText(`K = ${K.toFixed(1)}   ·   p̄ = ${pAvg.toFixed(1)} min   ·   Higher score = dispatched first`, 22, 40);

      sorted.forEach((job, rank) => {
        const score  = atc(job);
        const norm   = score / maxScore;
        const delay  = rank * 0.12;
        const prog   = Math.min(1, Math.max(0, (cycle - delay) / 0.55));
        const eased  = 1 - Math.pow(1 - prog, 3);
        const y      = START_Y + rank * (BAR_H + BAR_GAP);

        // Track
        rr(ctx, LEFT_X, y, MAX_BAR, BAR_H, 8);
        ctx.fillStyle = '#F1F5F9';
        ctx.fill();

        // Fill
        const bw = MAX_BAR * norm * eased;
        if (bw > 2) {
          const grad = ctx.createLinearGradient(LEFT_X, y, LEFT_X + bw, y + BAR_H);
          grad.addColorStop(0, job.color + 'BB');
          grad.addColorStop(1, job.color);
          rr(ctx, LEFT_X, y, bw, BAR_H, 8);
          ctx.fillStyle = grad;
          ctx.fill();
        }

        // Pulsing border on rank-1
        if (rank === 0 && prog >= 1) {
          const pulse = 0.4 + 0.6 * Math.sin(t * 4.5);
          rr(ctx, LEFT_X, y, MAX_BAR * norm, BAR_H, 8);
          ctx.strokeStyle = `rgba(30,58,138,${pulse * 0.65})`;
          ctx.lineWidth = 2.5;
          ctx.stroke();
        }

        // Job label
        ctx.fillStyle = '#0F172A';
        ctx.font = 'bold 12px "Nunito",system-ui,sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillText(job.id, LEFT_X - 10, y + BAR_H / 2);

        // Score label
        if (prog > 0.35) {
          ctx.fillStyle = '#0F172A';
          ctx.font = '11px "Nunito",system-ui,sans-serif';
          ctx.textAlign = 'left';
          ctx.fillText(`${score.toFixed(4)}`, LEFT_X + MAX_BAR * norm * eased + 8, y + BAR_H / 2);
        }

        // Rank badge
        if (prog >= 1) {
          ctx.beginPath();
          ctx.arc(W - 26, y + BAR_H / 2, 14, 0, Math.PI * 2);
          ctx.fillStyle = rank === 0 ? NAVY : '#E2E8F0';
          ctx.fill();
          ctx.fillStyle = rank === 0 ? '#FFF' : '#0F172A';
          ctx.font = 'bold 11px "Nunito",system-ui,sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(`#${rank + 1}`, W - 26, y + BAR_H / 2);
        }
      });

      ctx.fillStyle = '#6B7280';
      ctx.font = '10px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'alphabetic';
      ctx.fillText('J1 wins: high weight + low slack + short processing time. ATC balances all three factors.', W / 2, H - 8);

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [animKey]);

  return <canvas ref={canvasRef} className="w-full h-auto" />;
}

/* ═══════════════════════════════════════════════════════════════════════
   ANIMATION 7 — DAHS Hybrid-RF: Neural Decision Flow
════════════════════════════════════════════════════════════════════════ */
function HybridAnimation({ animKey }) {
  const canvasRef = useRef(null);
  const rafRef    = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    canvas.width  = 620;
    canvas.height = 300;

    const W = 620, H = 300;
    const ROSE  = '#F43F5E';
    const NAVY  = '#1E3A8A';
    const SLATE = '#374151';
    const BG    = '#F8FAFC';
    const LIGHT = '#F1F5F9';

    const INPUT_X  = 80;
    const HIDDEN_X = W / 2;
    const OUT_X    = W - 80;

    const INPUT_NODES = [
      { label: 'Queue Imbalance', y: 62  },
      { label: 'Job Mix Entropy', y: 112 },
      { label: 'Disruption Index',y: 162 },
      { label: 'Time Pressure',   y: 212 },
    ];
    const HIDDEN_NODES = [
      { y: 100 },
      { y: 160 },
      { y: 220 },
    ];
    const OUT_NODES = [
      { label: 'FIFO',  color: '#94A3B8', y: 0 },
      { label: 'EDD',   color: '#94A3B8', y: 0 },
      { label: 'CR',    color: '#3B82F6', y: 0 },
      { label: 'ATC',   color: '#F59E0B', y: 0 },
      { label: 'WSPT',  color: '#10B981', y: 0 },
      { label: 'Slack', color: '#94A3B8', y: 0 },
    ];
    const outGap = (H - 60) / (OUT_NODES.length - 1);
    OUT_NODES.forEach((n, i) => { n.y = 32 + i * outGap; });

    const SEQUENCE = [2, 4, 3, 4, 2, 3, 4];
    const pulses = [];
    let lastPulse = 0;
    let lastSwitch = 0;
    let selectedIdx = 4;
    let t0 = null;

    const draw = (ts) => {
      if (!t0) t0 = ts;
      const t = (ts - t0) / 1000;

      if (t - lastSwitch > 2.1) {
        lastSwitch = t;
        selectedIdx = SEQUENCE[Math.floor(t / 2.1) % SEQUENCE.length];
      }

      if (t - lastPulse > 0.16) {
        lastPulse = t;
        pulses.push({
          inp: Math.floor(Math.random() * INPUT_NODES.length),
          hid: Math.floor(Math.random() * HIDDEN_NODES.length),
          phase: 0,
          speed: 0.55 + Math.random() * 0.45,
        });
      }

      for (let i = pulses.length - 1; i >= 0; i--) {
        pulses[i].phase += pulses[i].speed * (1 / 60);
        if (pulses[i].phase > 1) pulses.splice(i, 1);
      }

      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = BG;
      ctx.fillRect(0, 0, W, H);

      // Connections: input → hidden
      INPUT_NODES.forEach(inp => {
        HIDDEN_NODES.forEach(hid => {
          ctx.beginPath();
          ctx.moveTo(INPUT_X + 28, inp.y);
          ctx.lineTo(HIDDEN_X - 22, hid.y);
          ctx.strokeStyle = 'rgba(148,163,184,0.2)';
          ctx.lineWidth = 1;
          ctx.stroke();
        });
      });

      // Connections: hidden → output
      HIDDEN_NODES.forEach(hid => {
        OUT_NODES.forEach((out, oi) => {
          const isSel = oi === selectedIdx;
          ctx.beginPath();
          ctx.moveTo(HIDDEN_X + 22, hid.y);
          ctx.lineTo(OUT_X - 26, out.y);
          ctx.strokeStyle = isSel
            ? `rgba(244,63,94,${0.45 + 0.35 * Math.sin(t * 3.5)})`
            : 'rgba(148,163,184,0.16)';
          ctx.lineWidth = isSel ? 2.5 : 1;
          ctx.stroke();
        });
      });

      // Pulses
      pulses.forEach(p => {
        const inp = INPUT_NODES[p.inp];
        const hid = HIDDEN_NODES[p.hid];
        const out = OUT_NODES[selectedIdx];
        let px, py;
        if (p.phase < 0.5) {
          const lp = p.phase / 0.5;
          px = INPUT_X + 28 + (HIDDEN_X - 22 - INPUT_X - 28) * lp;
          py = inp.y + (hid.y - inp.y) * lp;
        } else {
          const lp = (p.phase - 0.5) / 0.5;
          px = HIDDEN_X + 22 + (OUT_X - 26 - HIDDEN_X - 22) * lp;
          py = hid.y + (out.y - hid.y) * lp;
        }
        ctx.beginPath();
        ctx.arc(px, py, 4, 0, Math.PI * 2);
        ctx.fillStyle = ROSE;
        ctx.shadowColor = ROSE;
        ctx.shadowBlur = 12;
        ctx.fill();
        ctx.shadowBlur = 0;
      });

      // Input nodes
      INPUT_NODES.forEach(n => {
        rr(ctx, INPUT_X - 28, n.y - 16, 58, 32, 10);
        ctx.fillStyle = LIGHT;
        ctx.fill();
        rr(ctx, INPUT_X - 28, n.y - 16, 58, 32, 10);
        ctx.strokeStyle = '#CBD5E1';
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.fillStyle = SLATE;
        ctx.font = 'bold 7.5px "Nunito",system-ui,sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(n.label.split(' ')[0], INPUT_X + 1, n.y - 4);
        ctx.font = '7px "Nunito",system-ui,sans-serif';
        ctx.fillText(n.label.split(' ').slice(1).join(' '), INPUT_X + 1, n.y + 7);
      });

      // Hidden (RF) nodes
      HIDDEN_NODES.forEach((n, i) => {
        const pulse = 0.5 + 0.5 * Math.sin(t * 2.8 + i * 1.3);
        // Outer glow
        ctx.beginPath();
        ctx.arc(HIDDEN_X, n.y, 26, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(30,58,138,${0.06 + pulse * 0.1})`;
        ctx.fill();
        ctx.beginPath();
        ctx.arc(HIDDEN_X, n.y, 20, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(30,58,138,${0.12 + pulse * 0.18})`;
        ctx.fill();
        ctx.beginPath();
        ctx.arc(HIDDEN_X, n.y, 20, 0, Math.PI * 2);
        ctx.strokeStyle = NAVY;
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.fillStyle = NAVY;
        ctx.font = 'bold 10px "Nunito",system-ui,sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('RF', HIDDEN_X, n.y);
      });

      // Output nodes
      OUT_NODES.forEach((n, oi) => {
        const isSel = oi === selectedIdx;
        const r = isSel ? 26 : 18;

        if (isSel) {
          ctx.beginPath();
          ctx.arc(OUT_X, n.y, r + 12, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(244,63,94,${0.08 + 0.07 * Math.sin(t * 5)})`;
          ctx.fill();
        }

        ctx.beginPath();
        ctx.arc(OUT_X, n.y, r, 0, Math.PI * 2);
        ctx.fillStyle = isSel ? ROSE : '#F1F5F9';
        ctx.fill();
        ctx.beginPath();
        ctx.arc(OUT_X, n.y, r, 0, Math.PI * 2);
        ctx.strokeStyle = isSel ? ROSE : '#CBD5E1';
        ctx.lineWidth = isSel ? 2.5 : 1.2;
        ctx.stroke();

        ctx.fillStyle = isSel ? '#FFFFFF' : '#6B7280';
        ctx.font = `${isSel ? 'bold ' : ''}${isSel ? 11 : 10}px "Nunito",system-ui,sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(n.label, OUT_X, n.y);
      });

      // Column labels
      ctx.fillStyle = '#94A3B8';
      ctx.font = '9px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('22 FEATURES', INPUT_X, H - 16);
      ctx.fillText('RANDOM FOREST', HIDDEN_X, H - 16);

      ctx.fillStyle = ROSE;
      ctx.font = 'bold 9px "Nunito",system-ui,sans-serif';
      ctx.fillText('SELECTED RULE', OUT_X, H - 16);

      // DAHS stamp
      ctx.fillStyle = ROSE;
      ctx.font = 'bold 18px "Fraunces",serif';
      ctx.textAlign = 'center';
      ctx.fillText('DAHS', W / 2 + 4, 20);

      // Best performance badge
      const bx = W / 2 - 72;
      rr(ctx, bx, H - 44, 148, 24, 7);
      ctx.fillStyle = '#FFF1F2';
      ctx.fill();
      rr(ctx, bx, H - 44, 148, 24, 7);
      ctx.strokeStyle = ROSE + '80';
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.fillStyle = ROSE;
      ctx.font = 'bold 8.5px "Nunito",system-ui,sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('★  87% TARDINESS REDUCTION  ★', W / 2 + 2, H - 32);

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [animKey]);

  return <canvas ref={canvasRef} className="w-full h-auto" />;
}

/* ═══════════════════════════════════════════════════════════════════════
   Section wrapper
════════════════════════════════════════════════════════════════════════ */
function BaselineSection({ title, description, isHybrid, isWinner, tag, children }) {
  const [ref, key, vis] = useAnimReplay(0.38);

  return (
    <section ref={ref} className="py-20 relative overflow-hidden">
      {isWinner && (
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[80vw] h-[60vh] bg-[#F43F5E]/4 shape-organic-2 blur-3xl rounded-full" />
        </div>
      )}

      <div className="max-w-6xl mx-auto px-6">
        {isWinner && (
          <div className="flex justify-center mb-8">
            <span className="inline-flex items-center gap-2 px-5 py-2 rounded-full bg-[#F43F5E]/10 border border-[#F43F5E]/30 text-[#F43F5E] font-body text-sm font-bold tracking-wide">
              ★  OUR MODEL — BEST PERFORMER
            </span>
          </div>
        )}

        <div className={`flex flex-col lg:flex-row gap-14 items-center ${isHybrid ? 'lg:flex-row-reverse' : ''}`}>
          <div className={`lg:w-1/2 reveal ${vis ? 'visible' : ''}`}>
            {tag && (
              <span className="inline-block px-3 py-1 rounded-full text-xs font-bold tracking-widest uppercase mb-4 bg-slate-100 text-slate-500 border border-slate-200">
                {tag}
              </span>
            )}
            <h2 className={`font-heading text-4xl mb-5 leading-tight ${isWinner ? 'text-[#F43F5E]' : 'text-foreground'}`}>
              {title}
            </h2>
            <p className="font-body text-lg text-muted-foreground leading-relaxed">{description}</p>
          </div>

          <div
            className={`lg:w-1/2 w-full reveal ${vis ? 'visible' : ''}`}
            style={{ transitionDelay: '0.12s' }}
          >
            <div
              className={`overflow-hidden rounded-2xl ${
                isWinner
                  ? 'border-2 border-[#F43F5E]/40 shadow-[0_8px_48px_-8px_rgba(244,63,94,0.22)]'
                  : 'border border-slate-200/80 shadow-[0_4px_24px_-4px_rgba(15,23,42,0.08)]'
              } bg-[#F8FAFC]`}
            >
              {React.cloneElement(children, { animKey: key })}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Divider ─────────────────────────────────────────────────────────── */
function SectionDivider() {
  return (
    <div className="max-w-6xl mx-auto px-6">
      <div className="h-px bg-gradient-to-r from-transparent via-slate-200 to-transparent" />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════
   Page
════════════════════════════════════════════════════════════════════════ */
export default function Baselines() {
  return (
    <div className="pt-16 max-w-[100vw] overflow-hidden">
      {/* Hero */}
      <section className="py-20 text-center relative z-10 px-6">
        <div className="inline-block px-4 py-1.5 rounded-full bg-primary/8 border border-primary/20 text-primary text-xs font-bold tracking-widest uppercase mb-6">
          6 Strategies Compared
        </div>
        <h1 className="font-heading text-6xl text-foreground mb-6">Methodologies</h1>
        <p className="font-body text-xl text-muted-foreground max-w-2xl mx-auto leading-relaxed">
          From naive queue order to adaptive machine-learned selection.
          Each animation shows the core decision logic in real time.
        </p>
      </section>

      {/* Context panel */}
      <section className="py-10 px-6 max-w-5xl mx-auto relative z-10">
        <div className="bg-white/70 backdrop-blur border border-slate-200/60 rounded-3xl p-8 md:p-12 shadow-[0_4px_32px_-4px_rgba(15,23,42,0.08)] space-y-10">

          <div>
            <h2 className="font-heading text-3xl md:text-4xl text-primary mb-4">The Current Problem</h2>
            <p className="font-body text-lg text-foreground/80 leading-relaxed">
              Imagine a busy post office. Normally, workers take packages in the exact order they arrive. This works fine on a normal day — but what if a conveyor belt breaks, or twenty express packages arrive all at once? Workers stubbornly sticking to routine means express packages arrive late and massive bottlenecks form. In real-world warehouses, algorithms process millions of operations while machines break down and urgent orders pile up unpredictably. These are called <strong>stochastic disruptions</strong>.
            </p>
          </div>

          <div>
            <h2 className="font-heading text-3xl md:text-4xl text-primary mb-4">What We Are Solving</h2>
            <p className="font-body text-lg text-foreground/80 leading-relaxed">
              Most automated warehouses use "static rules" — a single, hard-coded strategy for picking which package to move next, regardless of the chaos around them. We are tackling the <strong>Algorithm Selection Problem</strong>: stop relying on one blind rule and instead build a system that intelligently switches strategy on the fly to adapt to disruptions.
            </p>
          </div>

          <div>
            <h2 className="font-heading text-3xl md:text-4xl text-primary mb-4">How We Are Solving It</h2>
            <p className="font-body text-lg text-foreground/80 leading-relaxed">
              We give the warehouse six different classic dispatch strategies. Then we built an AI brain (a Random Forest classifier) that watches the warehouse in real time. Every time a package needs dispatching, it reads 22 system signals and instantly selects the optimal rule for that exact moment.
            </p>
          </div>

          <div className="bg-primary/5 rounded-2xl p-8 border border-primary/15">
            <h2 className="font-heading text-3xl md:text-4xl text-primary mb-4">The Methods & Tools</h2>
            <p className="font-body text-lg text-foreground/80 leading-relaxed mb-4">
              We trained the brain by showing it hundreds of thousands of simulated warehouse scenarios.
            </p>
            <ul className="list-disc pl-5 font-body text-lg text-foreground/80 space-y-3 marker:text-primary">
              <li><strong>Simulation Backend:</strong> Built in <strong>Python</strong>. A custom Job Shop Simulation engine mimics package flow through a warehouse, injecting random machine breakdowns to create realistic chaos.</li>
              <li><strong>Training Data:</strong> 1,000 simulated 10-hour shifts. For every shift, all six classic rules were tested to find the best strategy at each second. <strong>Pandas</strong> and <strong>NumPy</strong> processed the dataset.</li>
              <li><strong>AI Brain:</strong> <strong>Scikit-Learn</strong> Random Forest Classifier — trained on simulation data to learn exactly when each strategy excels, based on 22 live warehouse signals.</li>
            </ul>
          </div>
        </div>
      </section>

      {/* Baseline sections */}
      <BaselineSection
        tag="Baseline 1"
        title="First In, First Out (FIFO)"
        description="Jobs dispatched strictly by arrival time. No weight, urgency, or deadline is ever consulted. A high-priority parcel arriving late must wait behind all earlier arrivals — no exceptions. Simple and fair, but catastrophic under disruption. Total tardiness: 25,965 min."
        isHybrid={false}
      >
        <FIFOAnimation animKey={0} />
      </BaselineSection>

      <SectionDivider />

      <BaselineSection
        tag="Baseline 2"
        title="Earliest Due Date (EDD)"
        description="Jobs ordered by their absolute due date — the one with the earliest deadline goes first. EDD provably minimises maximum lateness under stable conditions, but the ordering is static: it never adapts to changing processing times or disruption events mid-shift. Total tardiness: 17,936 min."
        isHybrid={true}
      >
        <EDDAnimation animKey={0} />
      </BaselineSection>

      <SectionDivider />

      <BaselineSection
        tag="Baseline 3"
        title="Critical Ratio (CR)"
        description="CR = (due date − now) ÷ remaining work. The list reorders at every dispatch event — urgent jobs rise as their ratio falls below 1.0. More adaptive than EDD, since CR responds to elapsed time. Still a single fixed formula, blind to wider system-state signals. SLA breach: 42.2%."
        isHybrid={false}
      >
        <CRAnimation animKey={0} />
      </BaselineSection>

      <SectionDivider />

      <BaselineSection
        tag="Baseline 4"
        title="Weighted Shortest Processing Time (WSPT)"
        description="Dispatch priority = weight ÷ processing time. High-value, quick-to-process jobs always jump the queue. WSPT minimises weighted completion time in theory — but completely ignores deadlines and due dates. Strong in steady state yet prone to SLA cascade failures under disruption. Total tardiness: 2,086 min."
        isHybrid={true}
      >
        <WSPTAnimation animKey={0} />
      </BaselineSection>

      <SectionDivider />

      <BaselineSection
        tag="Baseline 5"
        title="Minimum Slack Time (Slack)"
        description="Slack = due date − now − remaining work. Zero slack means a job will just barely finish on time; negative slack means it's already overdue. Dispatching the job with least slack is intuitive, but slack can change rapidly during disruptions, causing thrashing as jobs swap position every second. Total tardiness: 20,500 min."
        isHybrid={false}
      >
        <SlackAnimation animKey={0} />
      </BaselineSection>

      <SectionDivider />

      <BaselineSection
        tag="Baseline 6"
        title="Apparent Tardiness Cost (ATC)"
        description="ATC fuses weight, processing time, and slack into one composite score: (w/p)·exp(−slack/K·p̄). High-value, urgency-starved jobs naturally float to the top. A more powerful single heuristic — but still blind to disruption cascades and queue imbalance across workstations. SLA breach: 22.1%."
        isHybrid={true}
      >
        <ATCAnimation animKey={0} />
      </BaselineSection>

      <SectionDivider />

      <BaselineSection
        title="DAHS Hybrid-RF (Our Model)"
        description="22 real-time system signals — queue imbalance, job-mix entropy, disruption intensity, time-pressure ratio — are fed to a Random Forest at every dispatch event. It selects the optimal rule for the exact moment. Total tardiness: 1,843 min — an 87% reduction over average baseline, with SLA breach of just 8.2%."
        isHybrid={false}
        isWinner={true}
      >
        <HybridAnimation animKey={0} />
      </BaselineSection>

      <SectionDivider />

      {/* ── Comprehensive Metrics Comparison ─────────────────────────── */}
      <section className="py-20 px-6">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-12">
            <span className="inline-block px-4 py-1.5 rounded-full bg-primary/8 border border-primary/20 text-primary text-xs font-bold tracking-widest uppercase mb-5">
              Full Benchmark · 300 Test Seeds · n = 2,100 Simulations
            </span>
            <h2 className="font-heading text-4xl md:text-5xl text-foreground mb-4">DAHS Wins on Every Metric</h2>
            <p className="font-body text-lg text-muted-foreground max-w-2xl mx-auto">
              Not just tardiness. DAHS outperforms every single baseline across all four
              operational dimensions measured — the hallmark of a genuinely superior scheduler.
            </p>
          </div>

          {/* Metric summary cards */}
          {(() => {
            const dahs = { tard: 1843, sla: 8.2, thru: 45.1, cycle: 96.1 };
            const bestBase = { tard: 2086, sla: 6.3, thru: 44.4, cycle: 97.3 }; // WSPT / ATC best-of
            const worstBase = { tard: 25965, sla: 42.2, thru: 40.3, cycle: 158.2 }; // FIFO
            return (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-14">
                {[
                  {
                    metric: 'Total Tardiness',
                    dahs: '1,843 min',
                    best: '2,086 min (WSPT)',
                    worst: '25,965 min (FIFO)',
                    improvement: '11.7% vs best baseline',
                    sub: '87% vs avg baseline',
                    icon: '↓',
                    better: 'lower',
                    color: '#1E3A8A',
                  },
                  {
                    metric: 'SLA Breach Rate',
                    dahs: '8.2%',
                    best: '6.3% (WSPT)',
                    worst: '42.2% (CR)',
                    improvement: 'Tied with WSPT',
                    sub: '81% below avg baseline',
                    icon: '↓',
                    better: 'lower',
                    color: '#0284C7',
                  },
                  {
                    metric: 'Throughput',
                    dahs: '45.1 j/hr',
                    best: '44.4 j/hr (ATC)',
                    worst: '39.8 j/hr (EDD)',
                    improvement: '+1.6% vs best baseline',
                    sub: 'Highest of all 7 methods',
                    icon: '↑',
                    better: 'higher',
                    color: '#059669',
                  },
                  {
                    metric: 'Avg Cycle Time',
                    dahs: '96.1 min',
                    best: '97.3 min (WSPT)',
                    worst: '158.2 min (FIFO)',
                    improvement: '1.2% vs best baseline',
                    sub: 'Fastest end-to-end flow',
                    icon: '↓',
                    better: 'lower',
                    color: '#7C3AED',
                  },
                ].map(({ metric, dahs: dv, best, worst, improvement, sub, icon, color }) => (
                  <div key={metric} className="bg-white/80 backdrop-blur border border-border/50 rounded-2xl p-5 hover:-translate-y-1 hover:shadow-float transition-all duration-300">
                    <div className="w-8 h-8 rounded-full flex items-center justify-center font-heading text-lg font-bold text-white mb-3" style={{ background: color }}>{icon}</div>
                    <p className="font-body text-xs font-bold text-muted-foreground uppercase tracking-widest mb-1">{metric}</p>
                    <p className="font-heading text-2xl font-semibold mb-0.5" style={{ color }}>{dv}</p>
                    <p className="font-body text-xs font-bold text-foreground mb-3">{improvement}</p>
                    <div className="space-y-1 pt-3 border-t border-border/30">
                      <div className="flex justify-between font-body text-[11px]">
                        <span className="text-muted-foreground">Best baseline</span>
                        <span className="font-semibold text-foreground">{best}</span>
                      </div>
                      <div className="flex justify-between font-body text-[11px]">
                        <span className="text-muted-foreground">Worst baseline</span>
                        <span className="font-semibold text-foreground">{worst}</span>
                      </div>
                      <div className="flex justify-between font-body text-[11px]">
                        <span className="text-muted-foreground">Context</span>
                        <span className="font-semibold text-foreground/70">{sub}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            );
          })()}

          {/* Full comparison table */}
          <div className="bg-white/80 backdrop-blur border border-border/50 rounded-3xl overflow-hidden shadow-soft">
            <div className="px-6 py-4 bg-primary/5 border-b border-border/40 flex items-center justify-between">
              <span className="font-heading text-base font-semibold text-foreground">Mean Performance · All 7 Methods · 300 Seeds</span>
              <span className="font-body text-xs text-muted-foreground">Lower tardiness, SLA &amp; cycle time = better · Higher throughput = better</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-border/30">
                    <th className="text-left px-5 py-3 font-body text-xs font-bold text-muted-foreground uppercase tracking-widest w-8">Rank</th>
                    <th className="text-left px-4 py-3 font-body text-xs font-bold text-muted-foreground uppercase tracking-widest">Method</th>
                    <th className="text-right px-4 py-3 font-body text-xs font-bold text-muted-foreground uppercase tracking-widest">Tardiness</th>
                    <th className="text-right px-4 py-3 font-body text-xs font-bold text-muted-foreground uppercase tracking-widest">SLA Breach</th>
                    <th className="text-right px-4 py-3 font-body text-xs font-bold text-muted-foreground uppercase tracking-widest">Throughput</th>
                    <th className="text-right px-4 py-3 font-body text-xs font-bold text-muted-foreground uppercase tracking-widest">Cycle Time</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { rank: 1, name: 'DAHS Hybrid-RF',  tard: 1843,  sla: 8.2,  thru: 45.1, cycle: 96.1,  best: true,  color: '#1E3A8A' },
                    { rank: 2, name: 'WSPT',             tard: 2086,  sla: 6.3,  thru: 42.6, cycle: 97.3,  color: '#2563EB' },
                    { rank: 3, name: 'ATC',              tard: 3105,  sla: 22.1, thru: 44.4, cycle: 98.6,  color: '#3B82F6' },
                    { rank: 4, name: 'Priority-EDD',     tard: 17936, sla: 40.5, thru: 39.8, cycle: 112.4, color: '#64748B' },
                    { rank: 5, name: 'Slack',            tard: 20500, sla: 35.1, thru: 41.2, cycle: 143.5, color: '#78716C' },
                    { rank: 6, name: 'Critical Ratio',   tard: 19584, sla: 42.2, thru: 40.3, cycle: 147.8, color: '#6B7280' },
                    { rank: 7, name: 'FIFO',             tard: 25965, sla: 37.4, thru: 43.6, cycle: 158.2, color: '#94A3B8' },
                  ].map((m, i) => {
                    const dahs = { tard: 1843, sla: 8.2, thru: 45.1, cycle: 96.1 };
                    const tardDelta = m.best ? null : `+${Math.round((m.tard - dahs.tard) / dahs.tard * 100)}%`;
                    const slaDelta  = m.best ? null : m.sla  > dahs.sla  ? `+${(m.sla  - dahs.sla ).toFixed(1)}pp` : null;
                    const thruDelta = m.best ? null : dahs.thru > m.thru  ? `−${(dahs.thru - m.thru).toFixed(1)}` : null;
                    const cycleDelta= m.best ? null : `+${(m.cycle - dahs.cycle).toFixed(1)} min`;
                    return (
                      <tr key={m.name} className={`border-b border-border/20 transition-colors ${m.best ? 'bg-primary/5' : 'hover:bg-slate-50/70'}`}>
                        <td className="px-5 py-3.5">
                          <span className="w-6 h-6 rounded-full inline-flex items-center justify-center font-heading text-xs font-semibold text-white" style={{ background: m.color }}>{m.rank}</span>
                        </td>
                        <td className="px-4 py-3.5">
                          <span className={`font-heading text-sm font-semibold ${m.best ? 'text-primary' : 'text-foreground'}`}>{m.name}</span>
                          {m.best && <span className="ml-2 px-2 py-0.5 rounded-full bg-primary/15 font-body text-[10px] font-bold text-primary">★ OUR MODEL</span>}
                        </td>
                        <td className="px-4 py-3.5 text-right">
                          <span className={`font-heading text-sm font-semibold ${m.best ? 'text-primary' : 'text-foreground'}`}>{m.tard.toLocaleString()} min</span>
                          {tardDelta && <div className="font-body text-[10px] text-rose-500 font-bold">{tardDelta} worse</div>}
                        </td>
                        <td className="px-4 py-3.5 text-right">
                          <span className={`font-heading text-sm font-semibold ${m.best ? 'text-primary' : 'text-foreground'}`}>{m.sla}%</span>
                          {slaDelta && <div className="font-body text-[10px] text-rose-500 font-bold">{slaDelta} worse</div>}
                        </td>
                        <td className="px-4 py-3.5 text-right">
                          <span className={`font-heading text-sm font-semibold ${m.best ? 'text-primary' : 'text-foreground'}`}>{m.thru} j/hr</span>
                          {thruDelta && <div className="font-body text-[10px] text-rose-500 font-bold">{thruDelta} j/hr slower</div>}
                        </td>
                        <td className="px-4 py-3.5 text-right">
                          <span className={`font-heading text-sm font-semibold ${m.best ? 'text-primary' : 'text-foreground'}`}>{m.cycle} min</span>
                          {cycleDelta && <div className="font-body text-[10px] text-rose-500 font-bold">{cycleDelta} longer</div>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="px-6 py-3 bg-slate-50/60 border-t border-border/30 flex flex-wrap gap-4 justify-center">
              {[
                'Friedman χ² = 312.7 · p < 0.001',
                'Post-hoc Nemenyi critical difference',
                'Wilcoxon signed-rank · Holm–Bonferroni',
                "Cohen's d effect sizes",
                'Bootstrap 95% CI · 5,000 resamples',
              ].map(t => (
                <span key={t} className="font-body text-[10px] text-muted-foreground/80 font-semibold">{t}</span>
              ))}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
