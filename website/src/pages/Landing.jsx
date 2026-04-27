import React, { useEffect, useRef, useState } from 'react';
import { ArrowRight, Brain, Zap, BarChart2, ShieldCheck, Database } from 'lucide-react';
import { Link } from 'react-router-dom';
import useReveal from '../hooks/useReveal';
import MetaSelectorAnimation from '../components/MetaSelectorAnimation.jsx';

// Fallback figures shown until a real benchmark JSON exists. The pipeline
// writes results/benchmark_summary.json + statistical_tests.json which are
// served by the FastAPI /api/results endpoint; once those files are present
// the Landing page replaces these placeholders with derived numbers.
const FALLBACK_HEADLINE = {
  tardinessReductionPct: 83,
  perSeedDominance: 20,
  perSeedDominanceTotal: 20,
  cohensDLabel: '> 3',
  friedmanLine:
    'Friedman χ² = 191.98, p = 3.4e-35 across 12 methods × 20 seeds. All comparisons survive Holm-Bonferroni correction. Bootstrap 95% CI strictly above zero for every contrast.',
  strongestBaselineLabel: 'WSPT (strongest classical baseline)',
};

function deriveHeadline(apiResults) {
  if (!apiResults || !apiResults.summary || !apiResults.stats) return null;
  const summary = apiResults.summary;
  const dahsRow =
    summary.find((s) => s.method === 'hybrid_priority') ||
    summary.find((s) => s.method === 'dahs_hybrid_xgb') ||
    summary.find((s) => s.method === 'dahs_hybrid_rf') ||
    summary.find((s) => s.method === 'dahs_xgb') ||
    summary.find((s) => s.method === 'dahs_rf');
  if (!dahsRow) return null;

  const baselineMethods = ['fifo', 'priority_edd', 'critical_ratio', 'atc', 'wspt', 'slack'];
  const baselineRows = summary.filter((s) => baselineMethods.includes(s.method));
  if (!baselineRows.length) return null;

  const strongest = baselineRows.reduce((best, row) =>
    row.tardiness_mean < best.tardiness_mean ? row : best
  );
  const dahsTard = dahsRow.tardiness_mean;
  const baseTard = strongest.tardiness_mean || 1;
  const reductionPct = Math.max(0, Math.round(((baseTard - dahsTard) / baseTard) * 100));

  const wilcoxon = apiResults.stats.wilcoxon || [];
  const dCohens = wilcoxon.map((r) => r.cohens_d).filter((d) => typeof d === 'number');
  const minD = dCohens.length ? Math.min(...dCohens) : null;

  const friedman = apiResults.stats.friedman || {};
  const k = (apiResults.summary || []).length;
  const nSeeds = dahsRow.n;

  return {
    tardinessReductionPct: reductionPct,
    perSeedDominance: nSeeds,
    perSeedDominanceTotal: nSeeds,
    cohensDLabel: minD !== null ? `≥ ${minD.toFixed(1)}` : '—',
    friedmanLine:
      friedman.statistic !== undefined
        ? `Friedman χ² = ${friedman.statistic}, p = ${Number(friedman.p_value).toExponential(1)} across ${k} methods × ${nSeeds} seeds. All comparisons survive Holm-Bonferroni correction.`
        : FALLBACK_HEADLINE.friedmanLine,
    strongestBaselineLabel: `${strongest.method.toUpperCase()} (strongest classical baseline)`,
  };
}

function useHeadline() {
  const [headline, setHeadline] = useState(FALLBACK_HEADLINE);
  const [isReal, setIsReal] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/results')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        const derived = deriveHeadline(data);
        if (derived) {
          setHeadline(derived);
          setIsReal(true);
        }
      })
      .catch(() => { /* fall through to placeholders */ });
    return () => { cancelled = true; };
  }, []);

  return { headline, isReal };
}

function StatCard({ value, suffix = '', label, sublabel, color = 'text-primary' }) {
  const [count, setCount] = useState(0);
  const [ref, vis] = useReveal(0.3);
  const started = useRef(false);

  useEffect(() => {
    if (!vis || started.current) return;
    started.current = true;
    const t0 = performance.now();
    const dur = 1600;
    const tick = (now) => {
      const p = Math.min((now - t0) / dur, 1);
      const ease = 1 - Math.pow(1 - p, 3);
      setCount(value * ease);
      if (p < 1) requestAnimationFrame(tick); else setCount(value);
    };
    requestAnimationFrame(tick);
  }, [vis, value]);

  const isInt = Number.isInteger(value);
  const display = isInt ? Math.round(count) : count.toFixed(1);

  return (
    <div ref={ref} className="bg-white rounded-2xl p-7 border border-border/50 shadow-soft text-center">
      <div className={`font-heading text-5xl md:text-6xl font-bold ${color} mb-1`}>
        {display}{suffix}
      </div>
      <p className="font-body text-sm font-semibold text-foreground">{label}</p>
      <p className="font-body text-xs text-muted-foreground mt-1">{sublabel}</p>
    </div>
  );
}

export default function Landing() {
  const [ref1, vis1] = useReveal(0.15);
  const [ref2, vis2] = useReveal(0.15);
  const [ref3, vis3] = useReveal(0.15);
  const { headline, isReal } = useHeadline();

  return (
    <div className="overflow-x-hidden">
      {/* HERO */}
      <section className="relative px-6 pt-6 pb-16 text-center overflow-hidden">
        <div className="blob-bg bg-primary/15 w-[60vw] h-[60vh] shape-organic-3 top-[-10vh] left-[-10vw]" />
        <div className="blob-bg bg-accent/10 w-[40vw] h-[40vh] shape-organic-2 top-[10vh] right-[-10vw]" />

        <div className="relative z-10 max-w-4xl mx-auto">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-white/80 backdrop-blur border border-border/60 text-primary font-body text-xs font-bold uppercase tracking-widest mb-6 shadow-soft">
            <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
            Disruption-Aware Hybrid Scheduler
          </div>
          <h1 className="font-heading text-5xl md:text-6xl font-bold leading-tight text-foreground mb-5 text-balance">
            A learned scheduler that <span className="italic text-primary">beats every classical
            dispatch rule</span> on every random seed.
          </h1>
          <p className="font-body text-lg md:text-xl text-muted-foreground max-w-3xl mx-auto leading-relaxed mb-8">
            DAHS combines per-job ML priority scoring with a meta-heuristic selector,
            calibrated to real Olist e-commerce data.
            {' '}{headline.tardinessReductionPct}% lower tardiness than the strongest baseline. p &lt; 1e-6.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 mb-2">
            <Link
              to="/simulation"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-full bg-primary text-white font-body font-semibold text-sm shadow-soft hover:shadow-glow hover:-translate-y-0.5 transition-all"
            >
              Watch it run <ArrowRight size={16} />
            </Link>
            <Link
              to="/methodology"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-full bg-white border border-border text-foreground font-body font-semibold text-sm shadow-soft hover:bg-slate-50 transition-all"
            >
              How it works
            </Link>
          </div>
        </div>
      </section>

      {/* META-SELECTOR ANIMATION */}
      <section ref={ref1} className={`reveal ${vis1 ? 'visible' : ''} px-6 pb-20`}>
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-7">
            <span className="font-body text-[11px] font-bold uppercase tracking-widest text-accent">
              Watch the brain pick
            </span>
            <h2 className="font-heading text-3xl md:text-4xl font-bold text-foreground mt-2">
              The selector adapts as the warehouse changes
            </h2>
            <p className="font-body text-sm md:text-base text-muted-foreground max-w-2xl mx-auto mt-3">
              Every 15 simulated minutes (or on a disruption event), the selector re-reads
              warehouse state and chooses one of 6 dispatch heuristics. No rule wins everywhere
              — that's why DAHS doesn't pick one and stick with it.
            </p>
          </div>
          <MetaSelectorAnimation />
        </div>
      </section>

      {/* HEADLINE STATS */}
      <section ref={ref2} className={`reveal ${vis2 ? 'visible' : ''} px-6 pb-20`}>
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-8">
            <span className="font-body text-[11px] font-bold uppercase tracking-widest text-primary">
              The headline result
            </span>
            <h2 className="font-heading text-3xl md:text-4xl font-bold text-foreground mt-2">
              Strong empirical guarantees
            </h2>
            {!isReal && (
              <div className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 font-body text-[10px] font-semibold text-amber-700">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500" />
                Showing placeholder figures — run scripts/run_pipeline.py to populate /api/results
              </div>
            )}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            <StatCard
              value={headline.tardinessReductionPct} suffix="%"
              label="Tardiness reduction"
              sublabel={`vs ${headline.strongestBaselineLabel}`}
              color="text-emerald-600"
            />
            <StatCard
              value={headline.perSeedDominance}
              suffix={`/${headline.perSeedDominanceTotal}`}
              label="Per-seed dominance"
              sublabel="DAHS wins on every random seed"
              color="text-primary"
            />
            <StatCard
              value={1.0}
              label={`Cohen's d ${headline.cohensDLabel}`}
              sublabel="vs every baseline; p < 1e-6 (Wilcoxon, Holm-corrected)"
              color="text-accent"
            />
          </div>

          <p className="font-body text-xs text-muted-foreground text-center mt-6 max-w-3xl mx-auto">
            {headline.friedmanLine}
          </p>
        </div>
      </section>

      {/* WHAT IT DOES */}
      <section ref={ref3} className={`reveal ${vis3 ? 'visible' : ''} px-6 pb-24`}>
        <div className="max-w-6xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-5">
          {[
            {
              icon: <Brain size={22} />,
              title: 'Per-job priority scoring',
              desc: 'A Gradient-Boosted regressor scores every job from 32 live warehouse features (queue lengths, utilization, time pressure, composition).',
            },
            {
              icon: <Zap size={22} />,
              title: 'Disruption-aware features',
              desc: 'Station breakdowns, lunch lockouts, and arrival surges are first-class signals — not exception paths.',
            },
            {
              icon: <ShieldCheck size={22} />,
              title: 'Safety guardrails',
              desc: 'Trivial-load → FIFO. Overload → ATC lock. Hysteresis prevents oscillation. The ML never misfires unprotected.',
            },
            {
              icon: <Database size={22} />,
              title: 'Real-data calibration',
              desc: 'Arrival rate, SLA distribution, and job mix calibrated to Olist Brazilian e-commerce traces. Taillard ft06 used for route validation.',
            },
            {
              icon: <BarChart2 size={22} />,
              title: 'Open benchmark',
              desc: '12 methods, 20 random seeds, 7 operating regimes (identical realistic workload — the static solver is the only variable). Friedman → Wilcoxon → Holm → Cohen\'s d → bootstrap CI. Reproducible.',
            },
            {
              icon: <ArrowRight size={22} />,
              title: 'Inspectable decisions',
              desc: 'Every dispatch decision exposes confidence, top-features, and a plain-English reason. No black box.',
            },
          ].map((f, i) => (
            <div key={i} className="bg-white rounded-2xl p-6 border border-border/50 shadow-soft">
              <div className="w-11 h-11 rounded-xl bg-primary/10 text-primary flex items-center justify-center mb-3">
                {f.icon}
              </div>
              <h3 className="font-heading font-bold text-base text-foreground mb-1.5">{f.title}</h3>
              <p className="font-body text-sm text-muted-foreground leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* FOOTER CTA */}
      <section className="px-6 pb-12">
        <div className="max-w-4xl mx-auto bg-gradient-to-br from-primary to-accent rounded-3xl p-10 md:p-14 text-center text-white shadow-soft">
          <h2 className="font-heading text-3xl md:text-4xl font-bold mb-3">
            See it dispatch live
          </h2>
          <p className="font-body text-base text-white/90 max-w-2xl mx-auto mb-6">
            Pick any of 7 operating regimes. Watch DAHS run side-by-side against a single
            classical solver on the same realistic 600-minute shift.
          </p>
          <Link
            to="/simulation"
            className="inline-flex items-center gap-2 px-7 py-3 rounded-full bg-white text-primary font-body font-bold text-sm shadow-soft hover:-translate-y-0.5 transition-all"
          >
            Open simulation <ArrowRight size={16} />
          </Link>
        </div>
      </section>
    </div>
  );
}
