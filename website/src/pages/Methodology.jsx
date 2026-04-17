import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import useReveal from '../hooks/useReveal';

const HEURISTICS = [
  {
    name: 'FIFO', label: 'First-In First-Out',
    formula: 'sort by arrival_time ↑',
    color: '#94A3B8',
    citation: 'Standard queue discipline',
    citeFull: 'No specific citation — universal queue discipline employed as baseline.',
    whenBest: 'Uniform job mix, light load, no urgency differentiation.',
    whenWorst: 'Mixed priorities, tight deadlines, frequent breakdowns.',
    idx: 0,
  },
  {
    name: 'Priority-EDD', label: 'Earliest Due Date + Priority',
    formula: 'sort by (−priority_class, due_date) ↑',
    color: '#64748B',
    citation: 'Jackson (1955)',
    citeFull: 'Jackson, J.R. (1955). Scheduling a production line to minimize maximum tardiness. Management Research Project Report 43, UCLA.',
    whenBest: 'High express-order ratio (≥30%), tight deadlines, clear tier differentiation.',
    whenWorst: 'Uniform jobs, loose deadlines, low time pressure.',
    idx: 1,
  },
  {
    name: 'Critical Ratio', label: 'Critical Ratio',
    formula: 'CR = (due_date − now) / remaining_proc_time ↑',
    color: '#6B7280',
    citation: 'Pinedo (2016)',
    citeFull: 'Pinedo, M.L. (2016). Scheduling: Theory, Algorithms, and Systems. Springer, 5th ed. Also: Conway et al. (1967). Theory of Scheduling. Addison-Wesley.',
    whenBest: 'High breakdown rates causing dynamic urgency shifts per station.',
    whenWorst: 'Stable, uniform conditions where all CRs are similar.',
    idx: 2,
  },
  {
    name: 'ATC', label: 'Apparent Tardiness Cost',
    formula: '(w/p) × exp(−max(0, d−p−t) / K·p̄) ↓',
    color: '#3B82F6',
    citation: 'Vepsalainen & Morton (1987)',
    citeFull: 'Vepsalainen, A.P.J. & Morton, T.E. (1987). Priority rules for job shops with weighted tardiness costs. Management Science, 33(8), 1035-1047. doi:10.1287/mnsc.33.8.1035.',
    whenBest: 'Heavy load, high-weight jobs, tight deadlines, congested queues.',
    whenWorst: 'Light load, uniform weights — complexity is unnecessary.',
    idx: 3,
  },
  {
    name: 'WSPT', label: 'Weighted Shortest Processing Time',
    formula: 'sort by w/p ↓',
    color: '#2563EB',
    citation: 'Smith (1956)',
    citeFull: 'Smith, W.E. (1956). Various optimizers for single-stage production. Naval Research Logistics Quarterly, 3(1-2), 59-66. doi:10.1002/nav.3800030106. [Optimal for weighted completion time on single machine.]',
    whenBest: 'Many short, high-priority jobs; loose deadlines; throughput focus.',
    whenWorst: 'Extreme deadline pressure where avoiding tardiness trumps throughput.',
    idx: 4,
  },
  {
    name: 'Slack', label: 'Minimum Slack',
    formula: 'slack = due_date − now − remaining_proc_time ↑',
    color: '#78716C',
    citation: 'Pinedo (2016)',
    citeFull: 'Pinedo, M.L. (2016). Scheduling: Theory, Algorithms, and Systems. Springer, 5th ed. doi:10.1007/978-3-319-26580-3.',
    whenBest: 'Recovery mode: extreme deadline tightness, large backlog clearance.',
    whenWorst: 'Loose deadlines, steady flow — over-prioritizes near-tardy jobs.',
    idx: 5,
  },
];

const NOVEL_FEATURES = [
  {
    name: 'disruption_intensity',
    formula: '0.5 × (broken/5) + 0.25 × lunch_flag + 0.25 × |surge−1|',
    desc: 'Composite disruption score. Captures simultaneous breakdown severity, lunch-break operational slowdown, and arrival-surge deviation from baseline.',
    category: 'Disruption',
  },
  {
    name: 'queue_imbalance',
    formula: 'std(queue_sizes) / mean(queue_sizes)',
    desc: 'Coefficient of variation of queue depths across all 8 zones. High values indicate concentrated bottlenecks that favour urgency-aware rules.',
    category: 'Congestion',
  },
  {
    name: 'job_mix_entropy',
    formula: '−Σ p_k log₂ p_k   (k ∈ job types)',
    desc: 'Shannon entropy of job-type distribution in waiting queues. Low entropy (uniform mix) favours FIFO; high entropy (diverse mix) favours priority rules.',
    category: 'Diversity',
  },
  {
    name: 'time_pressure_ratio',
    formula: '|{j : CR_j < 1}| / n_waiting',
    desc: 'Fraction of waiting jobs whose Critical Ratio has fallen below 1.0 (already „behind schedule"). Values >0.4 strongly activate ATC or CR.',
    category: 'Urgency',
  },
];

function HeuristicCard({ h, expanded, onClick }) {
  return (
    <div
      className={`rounded-2xl border transition-all duration-300 overflow-hidden cursor-pointer
        ${expanded ? 'border-primary/40 shadow-soft' : 'border-border/50 hover:border-border'}`}
      onClick={onClick}
    >
      <div className="flex items-center justify-between px-6 py-5">
        <div className="flex items-center gap-4">
          <div className="w-3 h-3 rounded-full" style={{ background: h.color }} />
          <div>
            <span className="font-heading text-base font-semibold text-foreground">{h.name}</span>
            <span className="font-body text-sm text-muted-foreground ml-3">{h.label}</span>
          </div>
        </div>
        <div className={`w-8 h-8 rounded-full bg-muted flex items-center justify-center transition-transform duration-300 ${expanded ? 'rotate-180' : ''}`}>
          <ChevronDown size={14} className="text-primary" />
        </div>
      </div>

      {expanded && (
        <div className="px-6 pb-6 border-t border-border/30 pt-4 space-y-4 bg-white/60">
          <div className="inline-block px-3 py-1.5 rounded-lg bg-slate-900 text-green-400 font-mono text-xs">
            {h.formula}
          </div>
          {h.citation && h.citeFull && (
            <div className="flex items-start gap-2">
              <span className="text-[10px] font-bold px-2.5 py-1 rounded-full bg-blue-100 text-blue-700 shrink-0">[{h.citation}]</span>
              <p className="font-body text-xs text-muted-foreground italic leading-relaxed">{h.citeFull}</p>
            </div>
          )}
          <div className="grid md:grid-cols-2 gap-4">
            <div className="p-4 rounded-xl bg-green-50 border border-green-100">
              <p className="font-body text-xs font-bold text-green-700 mb-1 uppercase tracking-wider">✓ Best When</p>
              <p className="font-body text-sm text-green-800">{h.whenBest}</p>
            </div>
            <div className="p-4 rounded-xl bg-red-50 border border-red-100">
              <p className="font-body text-xs font-bold text-red-700 mb-1 uppercase tracking-wider">✗ Avoid When</p>
              <p className="font-body text-sm text-red-800">{h.whenWorst}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const GUARDRAILS = [
  {
    name: 'Trivial Load Guard',
    trigger: 'n_orders_in_system < 5',
    action: 'Override to FIFO',
    reason: 'ML inference is unnecessary noise with 5 or fewer jobs. FIFO is optimal for negligible load.',
    color: 'bg-blue-50 border-blue-200',
  },
  {
    name: 'Overload Guard',
    trigger: 'zone_utilization_avg > 0.92',
    action: 'Lock to ATC',
    reason: 'At >92% average utilisation, ATC\'s joint weight-urgency optimisation is consistently the best option. Avoids ML drift at extreme loads.',
    color: 'bg-orange-50 border-orange-200',
  },
  {
    name: 'OOD Detection Guard',
    trigger: 'Any feature outside training range ±10%',
    action: 'Fallback to ATC',
    reason: 'If production state is outside the ML training distribution, predictions are unreliable. ATC is a safe universal fallback.',
    color: 'bg-red-50 border-red-200',
  },
  {
    name: 'Hysteresis Guard',
    trigger: 'new_confidence < current_confidence + 0.15',
    action: 'Keep current heuristic',
    reason: 'Only switches if the new choice is ≥15% more confident. Prevents rapid oscillation under uncertainty.',
    color: 'bg-purple-50 border-purple-200',
  },
  {
    name: 'Starvation Prevention',
    trigger: 'Any job with wait_time > 60 min',
    action: 'Force-promote to front of queue',
    reason: 'Ensures no job is indefinitely neglected by the active heuristic, regardless of ML decision.',
    color: 'bg-yellow-50 border-yellow-200',
  },
];

export default function Methodology() {
  const [expanded, setExpanded] = useState(0);
  const [r1, v1] = useReveal();
  const [r2, v2] = useReveal();
  const [r3, v3] = useReveal();

  return (
    <div className="overflow-x-hidden">

      {/* ── HERO ──────────────────────────────────────────────────── */}
      <section className="relative min-h-[40vh] flex items-center justify-center text-center px-6 pt-8 pb-16 overflow-hidden">
        <div className="blob-bg bg-primary/10 w-[50vw] h-[50vh] shape-organic-2 top-[-8vh] left-[-5vw]" />
        <div className="relative z-10 max-w-3xl mx-auto">
          <div className="inline-flex items-center gap-2 px-5 py-2 rounded-full bg-white/70 backdrop-blur border border-border/60 text-primary font-body text-sm font-semibold mb-6 shadow-soft">
            <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
            Heuristics · Features · Guardrails · Data Pipeline
          </div>
          <h1 className="font-heading text-5xl md:text-6xl font-semibold leading-tight text-foreground mb-5">
            Archive of{' '}
            <span className="italic text-primary">Methodology</span>
          </h1>
          <p className="font-body text-lg text-muted-foreground max-w-2xl mx-auto leading-relaxed">
            A deep-dive into each dispatch heuristic, the four novel disruption-aware features,
            the snapshot-fork training algorithm, and the safety guardrails in DAHS 2.0.
          </p>
        </div>
      </section>

      {/* ── HEURISTICS ──────────────────────────────────────────────── */}
      <section ref={r1} className={`max-w-4xl mx-auto px-6 pb-20 reveal ${v1 ? 'visible' : ''}`}>
        <div className="mb-8">
          <div className="inline-block px-4 py-1.5 rounded-full bg-primary/10 text-primary text-sm font-bold mb-3">6 Dispatch Rules</div>
          <h2 className="font-heading text-3xl font-bold text-foreground mb-3">Baseline Heuristics</h2>
          <p className="font-body text-muted-foreground max-w-2xl">
            Click any heuristic to expand its formula, when to use it, and when to avoid it.
          </p>
        </div>

        <div className="space-y-3">
          {HEURISTICS.map((h, i) => (
            <HeuristicCard
              key={h.name}
              h={h}
              expanded={expanded === i}
              onClick={() => setExpanded(expanded === i ? -1 : i)}
            />
          ))}
        </div>
        <div className="mt-6 p-5 rounded-2xl bg-primary/5 border border-primary/20">
          <p className="font-body text-sm text-primary/80">
            <strong>Hyper-heuristic framework</strong> — ML selection over these 6 rules follows{' '}
            <span className="font-bold">[Burke et al. (2013)]</span>:{' '}
            <span className="italic">Hyper-heuristics: A survey of the state of the art.</span>{' '}
            Journal of the Operational Research Society, 64(12), 1695-1724. doi:10.1057/jors.2013.71.
          </p>
        </div>
      </section>

      {/* ── NOVEL FEATURES ──────────────────────────────────────────── */}
      <section ref={r2} className={`bg-foreground/[0.02] border-y border-border/40 py-20 reveal ${v2 ? 'visible' : ''}`}>
        <div className="max-w-5xl mx-auto px-6">
          <div className="mb-10">
            <div className="inline-block px-4 py-1.5 rounded-full bg-violet-100 text-violet-700 text-sm font-bold mb-3">4 Novel Features</div>
            <h2 className="font-heading text-3xl font-bold text-foreground mb-3">Disruption-Aware Features</h2>
            <p className="font-body text-muted-foreground max-w-2xl">
              DAHS_2 adds four novel features (F19–F22) to the standard 18-feature baseline.
              These capture disruption state explicitly, enabling the ML to reason about
              volatility that classical heuristics ignore.
            </p>
          </div>

          <div className="grid md:grid-cols-2 gap-5">
            {NOVEL_FEATURES.map((f, i) => (
              <div key={i} className="bg-white rounded-2xl border border-border/50 shadow-soft p-6 hover:-translate-y-1 transition-transform duration-200">
                <div className="flex items-center gap-3 mb-3">
                  <span className="inline-block px-3 py-1 rounded-full bg-violet-100 text-violet-700 text-[10px] font-bold uppercase tracking-wider">{f.category}</span>
                  <code className="font-mono text-sm font-bold text-foreground">{f.name}</code>
                </div>
                <div className="bg-slate-900 text-green-400 font-mono text-xs px-4 py-2.5 rounded-lg mb-3">
                  {f.formula}
                </div>
                <p className="font-body text-sm text-muted-foreground leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>

          <div className="mt-6 p-5 rounded-2xl bg-primary/5 border border-primary/20">
            <p className="font-body text-sm text-primary/80">
              <strong>22 total scenario features</strong> (F1–F18 system-state + F19–F22 disruption-aware)
              are extracted at each 15-minute re-evaluation window and fed to the heuristic selector.
            </p>
          </div>
        </div>
      </section>

      {/* ── GUARDRAILS ──────────────────────────────────────────────── */}
      <section ref={r3} className={`max-w-5xl mx-auto px-6 py-20 reveal ${v3 ? 'visible' : ''}`}>
        <div className="mb-10">
          <div className="inline-block px-4 py-1.5 rounded-full bg-red-100 text-red-700 text-sm font-bold mb-3">Safety-First Design</div>
          <h2 className="font-heading text-3xl font-bold text-foreground mb-3">Guardrails & Edge-Case Handling</h2>
          <p className="font-body text-muted-foreground max-w-2xl">
            The BatchwiseSelector checks 5 conditions before applying the ML prediction.
            These prevent misfiring in edge cases and ensure production-safe behaviour.
          </p>
        </div>

        <div className="space-y-4">
          {GUARDRAILS.map((g, i) => (
            <div key={i} className={`rounded-2xl border p-5 ${g.color} flex flex-col md:flex-row md:items-center gap-4`}>
              <div className="flex-1">
                <p className="font-heading text-base font-semibold text-foreground mb-1">{g.name}</p>
                <div className="flex flex-wrap gap-3 mb-2">
                  <span className="font-mono text-xs bg-slate-800 text-green-300 px-3 py-1 rounded">trigger: {g.trigger}</span>
                  <span className="font-mono text-xs bg-primary text-white px-3 py-1 rounded">→ {g.action}</span>
                </div>
                <p className="font-body text-sm text-muted-foreground">{g.reason}</p>
              </div>
            </div>
          ))}
        </div>

        <div className="mt-10 bg-white rounded-2xl border border-border/50 shadow-soft p-6">
          <h3 className="font-heading text-xl font-semibold text-foreground mb-4">Snapshot-Fork Training Algorithm</h3>
          <div className="grid md:grid-cols-2 gap-6">
            <div>
              <p className="font-body text-sm font-bold text-primary mb-2 uppercase tracking-wider">DAHS 1.0 (Old)</p>
              <ol className="space-y-1.5 font-body text-sm text-muted-foreground list-decimal list-inside">
                <li>Run full 10-hr simulation per heuristic (×6)</li>
                <li>Pick best heuristic for the entire day</li>
                <li>1 training label per scenario</li>
                <li>Model learns day-level patterns only</li>
              </ol>
            </div>
            <div>
              <p className="font-body text-sm font-bold text-primary mb-2 uppercase tracking-wider">DAHS 2.0 (New)</p>
              <ol className="space-y-1.5 font-body text-sm text-muted-foreground list-decimal list-inside">
                <li>Run base simulation; take snapshot every 10 min</li>
                <li>Fork each snapshot: run 6 heuristics × 20 min each</li>
                <li>Label snapshot with winning heuristic</li>
                <li>~60 labels per scenario (situation-level)</li>
              </ol>
            </div>
          </div>
        </div>
      </section>

    </div>
  );
}
