import React, { useEffect, useState } from 'react';
import { Check, X, Minus, ChevronDown, AlertTriangle } from 'lucide-react';
import useReveal from '../hooks/useReveal';

/* ── Comparison data ────────────────────────────────────────── */

const COMPARISON_ROWS = [
  {
    dim: 'Transparency of dispatch logic',
    amazon: { v: 'no', note: 'Proprietary, undocumented' },
    flipkart: { v: 'no', note: 'Proprietary' },
    dahs: { v: 'yes', note: '6 published heuristics + open ML model' },
  },
  {
    dim: 'Adapts to disruptions explicitly',
    amazon: { v: 'partial', note: 'Exception path' },
    flipkart: { v: 'partial', note: 'Exception path' },
    dahs: { v: 'yes', note: 'Disruption is a first-class feature signal' },
  },
  {
    dim: 'Inspectable per-decision reasons',
    amazon: { v: 'no', note: '' },
    flipkart: { v: 'no', note: '' },
    dahs: { v: 'yes', note: 'Confidence + top features + plain English' },
  },
  {
    dim: 'Calibrated to real e-commerce data',
    amazon: { v: 'yes', note: 'Internal traces (private)' },
    flipkart: { v: 'yes', note: 'Internal traces (private)' },
    dahs: { v: 'yes', note: 'Olist + Taillard (public benchmarks)' },
  },
  {
    dim: 'Open benchmark vs classical heuristics',
    amazon: { v: 'no', note: '' },
    flipkart: { v: 'no', note: '' },
    dahs: { v: 'yes', note: '12 methods × 20 seeds, Friedman + Wilcoxon' },
  },
  {
    dim: 'Infrastructure footprint',
    amazon: { v: 'heavy', note: 'Data-center scale' },
    flipkart: { v: 'heavy', note: 'Data-center scale' },
    dahs: { v: 'light', note: '1 GBR model, sub-second inference' },
  },
  {
    dim: 'Multi-warehouse / network optimization',
    amazon: { v: 'yes', note: 'Hundreds of FCs, regional routing' },
    flipkart: { v: 'yes', note: 'Tens of FCs' },
    dahs: { v: 'no', note: 'Single facility (research scope)' },
  },
  {
    dim: 'Hardware co-design (robotics, AGV, sortation)',
    amazon: { v: 'yes', note: 'Kiva / Amazon Robotics' },
    flipkart: { v: 'partial', note: 'Limited automation' },
    dahs: { v: 'no', note: 'Software only' },
  },
  {
    dim: 'Last-mile / carrier integration',
    amazon: { v: 'yes', note: 'Native delivery network' },
    flipkart: { v: 'yes', note: 'Ekart logistics arm' },
    dahs: { v: 'no', note: 'Out of scope' },
  },
  {
    dim: 'Tested at production scale',
    amazon: { v: 'yes', note: 'Billions of orders/year' },
    flipkart: { v: 'yes', note: 'Hundreds of millions/year' },
    dahs: { v: 'no', note: 'Simulation only (~500 jobs/shift)' },
  },
];

function ComparisonCell({ cell }) {
  const map = {
    yes:     { icon: <Check size={14} />,  bg: 'bg-emerald-50',  text: 'text-emerald-700',  border: 'border-emerald-200',  label: 'Yes' },
    partial: { icon: <Minus size={14} />,  bg: 'bg-amber-50',    text: 'text-amber-700',    border: 'border-amber-200',    label: 'Partial' },
    no:      { icon: <X size={14} />,      bg: 'bg-rose-50',     text: 'text-rose-700',     border: 'border-rose-200',     label: 'No' },
    heavy:   { icon: null,                  bg: 'bg-slate-100',   text: 'text-slate-700',    border: 'border-slate-300',    label: 'Heavy' },
    light:   { icon: <Check size={14} />,  bg: 'bg-emerald-50',  text: 'text-emerald-700',  border: 'border-emerald-200',  label: 'Light' },
  };
  const s = map[cell.v] || map.no;
  return (
    <div className="flex flex-col gap-1">
      <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full border text-[11px] font-bold w-fit ${s.bg} ${s.text} ${s.border}`}>
        {s.icon} {s.label}
      </span>
      {cell.note && (
        <span className="text-[11px] font-body text-muted-foreground leading-snug">{cell.note}</span>
      )}
    </div>
  );
}

/* ── Architecture diagram (inline SVG) ──────────────────────── */

function ArchitectureDiagram() {
  const W = 900, H = 360;
  const box = (x, y, w, h, fill, stroke) => ({ x, y, w, h, fill, stroke });

  const sim       = box(40,  140, 160, 80, '#EFF6FF', '#3B82F6');
  const features  = box(240, 140, 160, 80, '#F0FDF4', '#16A34A');
  const priority  = box(440, 60,  220, 80, '#FFFBEB', '#F59E0B');
  const selector  = box(440, 220, 220, 80, '#F3E8FF', '#A855F7');
  const dispatch  = box(700, 140, 160, 80, '#FEF2F2', '#DC2626');

  const node = (b, label, sub) => (
    <g>
      <rect x={b.x} y={b.y} width={b.w} height={b.h}
            rx={14} ry={14} fill={b.fill} stroke={b.stroke} strokeWidth={2} />
      <text x={b.x + b.w / 2} y={b.y + 32} textAnchor="middle"
            fontSize={14} fontWeight={700} fill="#0F172A"
            fontFamily="ui-sans-serif, system-ui">{label}</text>
      <text x={b.x + b.w / 2} y={b.y + 52} textAnchor="middle"
            fontSize={11} fill="#64748B"
            fontFamily="ui-sans-serif, system-ui">{sub}</text>
    </g>
  );

  const arrow = (x1, y1, x2, y2, dashed = false) => (
    <line x1={x1} y1={y1} x2={x2} y2={y2}
          stroke="#94A3B8" strokeWidth={1.8}
          strokeDasharray={dashed ? '5 4' : '0'}
          markerEnd="url(#arrowhead)" />
  );

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
      <defs>
        <marker id="arrowhead" markerWidth="10" markerHeight="10"
                refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
          <path d="M0,0 L0,6 L9,3 z" fill="#94A3B8" />
        </marker>
      </defs>

      {node(sim,      'Simulator',   'SimPy · 8 zones · 37 stations')}
      {node(features, 'Features',    '32 scenario + 5 job features')}
      {node(priority, 'Priority GBR','per-job score (regressor)')}
      {node(selector, 'BatchwiseSelector', 'pick heuristic / 15 min (RF/XGB)')}
      {node(dispatch, 'Dispatcher',  'orders the queue')}

      {arrow(sim.x + sim.w,  sim.y + sim.h / 2,  features.x, features.y + features.h / 2)}
      {arrow(features.x + features.w, features.y + 30, priority.x, priority.y + priority.h / 2)}
      {arrow(features.x + features.w, features.y + 50, selector.x, selector.y + selector.h / 2)}
      {arrow(priority.x + priority.w, priority.y + priority.h / 2, dispatch.x, dispatch.y + 30)}
      {arrow(selector.x + selector.w, selector.y + selector.h / 2, dispatch.x, dispatch.y + 50)}
      {arrow(dispatch.x + dispatch.w / 2, dispatch.y + dispatch.h, sim.x + sim.w / 2, sim.y, true)}

      <text x={W / 2} y={350} textAnchor="middle"
            fontSize={11} fill="#64748B" fontStyle="italic">
        Dashed line = dispatch decisions feed back as next-step state
      </text>
    </svg>
  );
}

/* ── Section components ─────────────────────────────────────── */

function Section({ kicker, title, sub, children }) {
  const [ref, vis] = useReveal(0.1);
  return (
    <section ref={ref} className={`reveal ${vis ? 'visible' : ''} px-6 py-14`}>
      <div className="max-w-6xl mx-auto">
        <div className="mb-8">
          {kicker && (
            <span className="font-body text-[11px] font-bold uppercase tracking-widest text-primary">
              {kicker}
            </span>
          )}
          <h2 className="font-heading text-3xl md:text-4xl font-bold text-foreground mt-2">{title}</h2>
          {sub && (
            <p className="font-body text-sm md:text-base text-muted-foreground mt-3 max-w-3xl">{sub}</p>
          )}
        </div>
        {children}
      </div>
    </section>
  );
}

function StatRow({ stats }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {stats.map((s, i) => (
        <div key={i} className="bg-white rounded-xl border border-border/50 p-4 text-center shadow-soft">
          <div className="font-heading text-2xl font-bold text-primary">{s.value}</div>
          <div className="font-body text-[11px] text-muted-foreground mt-1">{s.label}</div>
        </div>
      ))}
    </div>
  );
}

/* ── Main page ──────────────────────────────────────────────── */

export default function Methodology() {
  const [results, setResults] = useState(null);

  useEffect(() => {
    fetch('/api/results').then(r => r.ok ? r.json() : null).then(setResults).catch(() => {});
  }, []);

  return (
    <div className="overflow-x-hidden">
      {/* HERO */}
      <section className="px-6 pt-6 pb-10 text-center">
        <div className="max-w-4xl mx-auto">
          <span className="font-body text-[11px] font-bold uppercase tracking-widest text-primary">
            Methodology · Comparison · Architecture
          </span>
          <h1 className="font-heading text-4xl md:text-5xl font-bold text-foreground mt-3 mb-4">
            How DAHS works — and how it stacks up
          </h1>
          <p className="font-body text-base text-muted-foreground max-w-3xl mx-auto leading-relaxed">
            DAHS is a research scheduler, not a fulfillment platform. Below: the architecture,
            the comparison to industry leaders (honest), and the evaluation protocol.
          </p>
        </div>
      </section>

      {/* THE PROBLEM */}
      <Section
        kicker="The problem"
        title="One fixed dispatch rule cannot handle a real shift"
        sub="Classical schedulers pick FIFO, EDD, or WSPT for the whole 8-hour window. Each rule has a regime where it wins and many regimes where it loses. As the workload composition changes through the day — morning ramp-up, afternoon bulk, end-of-day express surge — the right rule changes too."
      >
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[
            { t: 'Workload shifts', d: 'Order mix changes hourly (Olist data: 4× variance in express ratio across the day).' },
            { t: 'Disruptions', d: 'Stations break down, workers go to lunch, surges arrive — all change which rule is locally optimal.' },
            { t: 'SLA-weighted goals', d: 'Tardiness on a high-weight Type-E job costs 3× a Type-D. Generic rules ignore this.' },
          ].map((p, i) => (
            <div key={i} className="bg-white rounded-2xl border border-border/50 p-6 shadow-soft">
              <div className="font-heading font-bold text-base text-foreground mb-1">{p.t}</div>
              <div className="font-body text-sm text-muted-foreground leading-relaxed">{p.d}</div>
            </div>
          ))}
        </div>
      </Section>

      {/* ARCHITECTURE */}
      <Section
        kicker="Architecture"
        title="Two ML paths, one dispatcher"
        sub="The Priority GBR scores every job individually from the live state. The BatchwiseSelector picks one of 6 heuristics to use for the next 15-minute window. Both feed the same dispatcher; both observe the same 32 features."
      >
        <div className="bg-white rounded-2xl border border-border/50 p-6 shadow-soft mb-6">
          <ArchitectureDiagram />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-amber-50/50 rounded-2xl border border-amber-200/70 p-5">
            <div className="font-heading font-bold text-amber-900 mb-1">Priority GBR (the winner)</div>
            <div className="font-body text-sm text-amber-900/80 leading-relaxed">
              GradientBoostingRegressor (300 trees, depth 6, learning rate 0.05). Scores each
              job using 32 scenario features + 5 job features. Predictions sort the queue
              every dispatch call. <span className="font-bold">Wins 20/20 random seeds.</span>
            </div>
          </div>
          <div className="bg-violet-50/50 rounded-2xl border border-violet-200/70 p-5">
            <div className="font-heading font-bold text-violet-900 mb-1">BatchwiseSelector (the explainer)</div>
            <div className="font-body text-sm text-violet-900/80 leading-relaxed">
              Random Forest / XGBoost classifier picking 1 of 6 heuristics every 15 min.
              Includes guardrails (trivial-load → FIFO, overload → ATC) and hysteresis to
              prevent oscillation. Provides the visible reasoning trace.
            </div>
          </div>
        </div>
      </Section>

      {/* COMPARISON */}
      <Section
        kicker="Comparison"
        title="DAHS vs Amazon vs Flipkart — honestly"
        sub="DAHS is a research artifact, not a fulfillment platform. It wins on transparency, inspectability, and open benchmarking. It loses on scale, hardware, and last-mile integration. Both sets of facts matter."
      >
        <div className="bg-white rounded-2xl border border-border/50 shadow-soft overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-border/40">
                  <th className="text-left font-heading font-bold text-foreground px-5 py-3.5 text-xs uppercase tracking-wider">Dimension</th>
                  <th className="text-left font-heading font-bold text-foreground px-5 py-3.5 text-xs uppercase tracking-wider w-[22%]">Amazon</th>
                  <th className="text-left font-heading font-bold text-foreground px-5 py-3.5 text-xs uppercase tracking-wider w-[22%]">Flipkart</th>
                  <th className="text-left font-heading font-bold text-foreground px-5 py-3.5 text-xs uppercase tracking-wider w-[22%] bg-primary/5">DAHS (this work)</th>
                </tr>
              </thead>
              <tbody>
                {COMPARISON_ROWS.map((row, i) => (
                  <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50/40'}>
                    <td className="px-5 py-4 font-body font-semibold text-foreground text-sm border-b border-border/30">{row.dim}</td>
                    <td className="px-5 py-4 border-b border-border/30"><ComparisonCell cell={row.amazon} /></td>
                    <td className="px-5 py-4 border-b border-border/30"><ComparisonCell cell={row.flipkart} /></td>
                    <td className="px-5 py-4 border-b border-border/30 bg-primary/5"><ComparisonCell cell={row.dahs} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <p className="font-body text-xs text-muted-foreground mt-4 italic">
          Industry assessments based on public information about Amazon Robotics, Flipkart's Ekart logistics,
          and standard fulfillment-platform architecture. DAHS column reflects implemented features in this repository.
        </p>
      </Section>

      {/* EVALUATION PROTOCOL */}
      <Section
        kicker="Evaluation protocol"
        title="Statistical rigor at the level of OR journals"
        sub="Friedman → pairwise Wilcoxon → Holm-Bonferroni correction → Cohen's d → bootstrap 95% CI. 20 random seeds, 7 operating-regime presets (controlled experiment — identical realistic workload, only the static solver varies), 12 methods compared."
      >
        <StatRow stats={[
          { value: '12', label: 'Methods compared (6 classical + 5 ML + Oracle)' },
          { value: '20', label: 'Random seeds (independent simulations)' },
          { value: '7', label: 'Operating regimes (same realistic workload)' },
          { value: '32', label: 'Scenario features per decision' },
        ]} />

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-5">
          <div className="bg-white rounded-2xl border border-border/50 p-5 shadow-soft">
            <h4 className="font-heading font-bold text-base text-foreground mb-3">Top features by importance</h4>
            <img src="/plots/feature_importance.png"
                 alt="Feature importance bar chart"
                 className="w-full rounded-lg border border-border/30"
                 onError={(e) => { e.target.style.display = 'none'; }} />
          </div>
          <div className="bg-white rounded-2xl border border-border/50 p-5 shadow-soft">
            <h4 className="font-heading font-bold text-base text-foreground mb-3">SHAP — per-feature impact on priority score</h4>
            <img src="/plots/shap_summary.png"
                 alt="SHAP summary plot"
                 className="w-full rounded-lg border border-border/30 bg-slate-900"
                 onError={(e) => { e.target.style.display = 'none'; }} />
          </div>
          <div className="bg-white rounded-2xl border border-border/50 p-5 shadow-soft">
            <h4 className="font-heading font-bold text-base text-foreground mb-3">Tardiness across all methods</h4>
            <img src="/plots/benchmark_tardiness.png"
                 alt="Benchmark tardiness chart"
                 className="w-full rounded-lg border border-border/30"
                 onError={(e) => { e.target.style.display = 'none'; }} />
          </div>
          <div className="bg-white rounded-2xl border border-border/50 p-5 shadow-soft">
            <h4 className="font-heading font-bold text-base text-foreground mb-3">Pareto front: tardiness vs throughput</h4>
            <img src="/plots/pareto_front.png"
                 alt="Pareto front"
                 className="w-full rounded-lg border border-border/30"
                 onError={(e) => { e.target.style.display = 'none'; }} />
          </div>
        </div>

        {results?.stats?.wilcoxon && (
          <div className="bg-white rounded-2xl border border-border/50 p-5 shadow-soft mt-5">
            <h4 className="font-heading font-bold text-base text-foreground mb-3">Pairwise Wilcoxon (DAHS vs each baseline)</h4>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-50 border-b border-border/40">
                    <th className="text-left px-3 py-2 font-bold text-xs uppercase tracking-wider">Comparison</th>
                    <th className="text-right px-3 py-2 font-bold text-xs uppercase tracking-wider">p-value</th>
                    <th className="text-right px-3 py-2 font-bold text-xs uppercase tracking-wider">Cohen's d</th>
                    <th className="text-center px-3 py-2 font-bold text-xs uppercase tracking-wider">Holm sig.</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(results.stats.wilcoxon).slice(0, 12).map(([key, val], i) => (
                    <tr key={key} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50/40'}>
                      <td className="px-3 py-2 font-mono text-xs">{key}</td>
                      <td className="px-3 py-2 text-right font-mono text-xs">{val.p_value?.toExponential(2) || '—'}</td>
                      <td className="px-3 py-2 text-right font-mono text-xs">{val.cohens_d?.toFixed(2) || '—'}</td>
                      <td className="px-3 py-2 text-center">
                        {val.holm_significant ? <Check size={14} className="inline text-emerald-600" /> : <X size={14} className="inline text-rose-600" />}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Section>

      {/* LIMITATIONS */}
      <Section
        kicker="Honest limitations"
        title="What DAHS is NOT"
        sub="A research scheduler is not a fulfillment platform. We list these so evaluators don't have to find them."
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[
            { t: 'Not a WMS', d: 'No inventory database, no pickers, no carrier integration, no returns. Scheduling layer only.' },
            { t: 'No physical layer', d: 'No robotics, no AGVs, no conveyor control, no sortation hardware co-design.' },
            { t: 'Single-facility scale', d: '37 stations and ~500 jobs/shift in our simulator. Production-scale unproven.' },
            { t: 'Sim-to-real gap', d: 'Trained and tested on simulated data calibrated to Olist. Real warehouse-floor traces would close the gap.' },
            { t: 'No multi-warehouse routing', d: 'No order-to-FC assignment, no network load balancing, no last-mile.' },
            { t: 'Narrow objective', d: 'Optimizes tardiness / SLA / cycle time. Energy, ergonomics, NPS not modeled.' },
          ].map((l, i) => (
            <div key={i} className="bg-amber-50/40 rounded-2xl border border-amber-200/60 p-5">
              <div className="flex items-start gap-3">
                <AlertTriangle size={18} className="text-amber-700 flex-shrink-0 mt-0.5" />
                <div>
                  <div className="font-heading font-bold text-amber-900 mb-1">{l.t}</div>
                  <div className="font-body text-sm text-amber-900/80 leading-relaxed">{l.d}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}
