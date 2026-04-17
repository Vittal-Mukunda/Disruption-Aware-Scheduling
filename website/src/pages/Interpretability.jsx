import React, { useState, useEffect, useRef } from 'react';
import { Brain, Shield, Zap, ChevronDown, ChevronRight } from 'lucide-react';
import useReveal from '../hooks/useReveal';

/* ── 3-Level Interpretability display ──────────────────────────── */
const EXAMPLE_DECISION = {
  time: 135.00,
  heuristic: 'atc',
  reason: 'ml_decision',
  confidence: 0.78,
  switched: true,
  plainEnglish: 'DAHS selected ATC (78% confidence) because 42% of jobs are nearing their deadlines (time_pressure_ratio=0.42). The warehouse is running at 81% average utilisation with 2 broken stations causing bottlenecks.',
  topFeatures: [
    { name: 'time_pressure_ratio',   importance: 0.187, value: 0.42 },
    { name: 'disruption_intensity',  importance: 0.143, value: 0.61 },
    { name: 'zone_utilization_avg',  importance: 0.118, value: 0.81 },
    { name: 'n_broken_stations',     importance: 0.096, value: 2.0  },
    { name: 'avg_priority_weight',   importance: 0.082, value: 2.14 },
  ],
  probabilities: {
    fifo: 0.03, priority_edd: 0.07, critical_ratio: 0.09,
    atc: 0.78, wspt: 0.02, slack: 0.01,
  },
  dtPath: [
    { feature: 'time_pressure_ratio', threshold: 0.35, direction: 'right', value: 0.42 },
    { feature: 'disruption_intensity',threshold: 0.55, direction: 'right', value: 0.61 },
    { feature: 'zone_utilization_avg',threshold: 0.75, direction: 'right', value: 0.81 },
  ],
  dtLeaf: 'ATC',
};

const HEURISTIC_COLORS = {
  fifo: '#94A3B8', priority_edd: '#64748B', critical_ratio: '#6B7280',
  atc: '#3B82F6', wspt: '#2563EB', slack: '#78716C',
};

/* ── DT Path visualizer ────────────────────────────────────────── */
function DtPathViz({ path, leaf }) {
  return (
    <div className="space-y-2">
      {path.map((node, i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="w-5 shrink-0 text-muted-foreground text-xs font-mono">{i + 1}.</div>
          <div className="flex-1 flex items-center gap-2 flex-wrap">
            <code className="bg-slate-900 text-green-400 font-mono text-xs px-2 py-1 rounded">{node.feature}</code>
            <span className="font-mono text-xs text-muted-foreground">{node.direction === 'right' ? '>' : '≤'}</span>
            <code className="bg-slate-100 text-foreground font-mono text-xs px-2 py-1 rounded">{node.threshold}</code>
            <ChevronRight size={12} className="text-muted-foreground" />
            <span className="font-mono text-xs text-primary">actual={node.value}</span>
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${node.direction === 'right' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
              {node.direction === 'right' ? 'TRUE →' : 'FALSE →'}
            </span>
          </div>
        </div>
      ))}
      <div className="flex items-center gap-3 pt-2 border-t border-border/30">
        <div className="w-5" />
        <div className="flex items-center gap-2">
          <span className="font-body text-xs text-muted-foreground">Leaf node:</span>
          <span
            className="font-bold text-sm px-3 py-1 rounded-lg text-white"
            style={{ background: HEURISTIC_COLORS[leaf?.toLowerCase()] || '#1e3a8a' }}
          >
            {leaf}
          </span>
        </div>
      </div>
    </div>
  );
}

function FeatureBar({ name, value, importance, maxImportance }) {
  const barW = Math.min((importance / maxImportance) * 100, 100);
  return (
    <div className="flex items-center gap-3">
      <div className="w-40 shrink-0">
        <p className="font-mono text-xs text-foreground truncate">{name}</p>
      </div>
      <div className="flex-1 h-3 bg-muted rounded-full overflow-hidden">
        <div className="h-full rounded-full bg-primary transition-all duration-700" style={{ width: `${barW}%` }} />
      </div>
      <div className="w-16 text-right">
        <span className="font-mono text-xs text-muted-foreground">{importance.toFixed(3)}</span>
      </div>
      <div className="w-14 text-right">
        <span className="font-mono text-xs font-bold text-primary">{value.toFixed(3)}</span>
      </div>
    </div>
  );
}

/* ── Feature names fetched from backend ─────────────────────────── */
function FeatureExplorer() {
  const [features, setFeatures] = useState([]);
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/feature-names')
      .then(r => r.ok ? r.json() : [])
      .then(data => { setFeatures(data); setLoading(false); })
      .catch(() => { setLoading(false); });
  }, []);

  const categories = ['all', ...new Set(features.map(f => f.category))];
  const filtered = selectedCategory === 'all' ? features : features.filter(f => f.category === selectedCategory);

  return (
    <div>
      <div className="flex gap-2 flex-wrap mb-5">
        {categories.map(c => (
          <button
            key={c}
            onClick={() => setSelectedCategory(c)}
            className={`px-4 py-1.5 rounded-full font-body text-xs font-semibold transition-all duration-200 ${
              selectedCategory === c
                ? 'bg-primary text-white'
                : 'bg-muted text-muted-foreground hover:bg-primary/10 hover:text-primary'
            }`}
          >
            {c.charAt(0).toUpperCase() + c.slice(1)}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="text-muted-foreground font-body text-sm animate-pulse">Loading features from backend…</p>
      ) : (
        <div className="space-y-3">
          {filtered.map((f, i) => (
            <div key={i} className="flex items-start gap-4 p-4 rounded-xl bg-white border border-border/40 hover:border-primary/30 transition-colors">
              <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary font-mono text-xs font-bold shrink-0">
                {(f.index + 1).toString().padStart(2, '0')}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  <code className="font-mono text-sm font-bold text-foreground">{f.name}</code>
                  <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider ${
                    f.category === 'disruption' ? 'bg-violet-100 text-violet-700' :
                    f.category === 'timing' ? 'bg-orange-100 text-orange-700' :
                    'bg-blue-100 text-blue-700'
                  }`}>
                    {f.category}
                    {f.name.includes('disruption') || f.name.includes('entropy') || f.name.includes('imbalance') || f.name.includes('pressure') ? ' · NOVEL' : ''}
                  </span>
                </div>
                <p className="font-body text-xs text-muted-foreground leading-relaxed">{f.description}</p>
              </div>
            </div>
          ))}
          {filtered.length === 0 && !loading && (
            <p className="text-muted-foreground text-sm font-body">Run the training pipeline to populate feature metadata.</p>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Heuristic description cards (fetched from backend) ─────────── */
function HeuristicCards() {
  const [heuristics, setHeuristics] = useState([]);
  const [expanded, setExpanded] = useState(null);

  useEffect(() => {
    fetch('/api/heuristic-info')
      .then(r => r.ok ? r.json() : [])
      .then(data => setHeuristics(data))
      .catch(() => {});
  }, []);

  return (
    <div className="grid md:grid-cols-2 gap-4">
      {heuristics.map((h, i) => (
        <div
          key={h.name}
          className={`rounded-2xl border p-5 cursor-pointer transition-all duration-200 ${
            expanded === i ? 'border-primary/40 shadow-soft' : 'border-border/40 hover:border-primary/20'
          }`}
          onClick={() => setExpanded(expanded === i ? null : i)}
        >
          <div className="flex items-center gap-3 mb-2">
            <div className="w-3 h-3 rounded-full shrink-0" style={{ background: h.color }} />
            <span className="font-heading text-base font-semibold text-foreground">{h.label}</span>
          </div>
          <code className="font-mono text-xs text-muted-foreground">{h.formula}</code>
          {expanded === i && (
            <div className="mt-4 grid grid-cols-2 gap-3">
              <div className="p-3 rounded-xl bg-green-50 border border-green-100">
                <p className="font-body text-[10px] font-bold text-green-700 mb-1 uppercase">✓ Best When</p>
                <p className="font-body text-xs text-green-800">{h.whenBest}</p>
              </div>
              <div className="p-3 rounded-xl bg-red-50 border border-red-100">
                <p className="font-body text-[10px] font-bold text-red-700 mb-1 uppercase">✗ Avoid When</p>
                <p className="font-body text-xs text-red-800">{h.whenWorst}</p>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default function Interpretability() {
  const [level, setLevel] = useState('all');
  const [r1, v1] = useReveal();
  const [r2, v2] = useReveal();
  const [r3, v3] = useReveal();
  const maxImportance = Math.max(...EXAMPLE_DECISION.topFeatures.map(f => f.importance));

  return (
    <div className="overflow-x-hidden">

      {/* ── HERO ──────────────────────────────────────────────────── */}
      <section className="relative min-h-[38vh] flex items-center justify-center text-center px-6 pt-8 pb-14 overflow-hidden">
        <div className="blob-bg bg-accent/20 w-[50vw] h-[45vh] shape-organic-1 top-[-5vh] right-[-5vw]" />
        <div className="relative z-10 max-w-3xl mx-auto">
          <div className="inline-flex items-center gap-2 px-5 py-2 rounded-full bg-white/70 backdrop-blur border border-border/60 text-primary font-body text-sm font-semibold mb-7 shadow-soft">
            <Brain size={14} className="text-primary" />
            3-Level Interpretability · Glass-box AI
          </div>
          <h1 className="font-heading text-5xl md:text-6xl font-semibold leading-tight text-foreground mb-5">
            Every Decision{' '}
            <span className="italic text-primary">Explained</span>
          </h1>
          <p className="font-body text-lg text-muted-foreground max-w-2xl mx-auto leading-relaxed">
            DAHS 2.0 provides three levels of explanation per heuristic selection:
            a plain English summary, feature attribution scores, and the full decision tree path.
          </p>
        </div>
      </section>

      {/* ── 3-LEVEL EXAMPLE DECISION ──────────────────────────────── */}
      <section ref={r1} className={`max-w-5xl mx-auto px-6 pb-16 reveal ${v1 ? 'visible' : ''}`}>
        <div className="mb-8">
          <div className="inline-block px-4 py-1.5 rounded-full bg-primary/10 text-primary text-sm font-bold mb-3">Live Example</div>
          <h2 className="font-heading text-3xl font-bold text-foreground mb-2">Example Decision at t=135 min</h2>
          <p className="font-body text-muted-foreground">Explore the three levels of explanation for a single batch-wise evaluation.</p>
        </div>

        {/* LEVEL 0: Status card */}
        <div className="mb-5 p-5 rounded-2xl bg-white border border-border/50 shadow-soft flex flex-wrap gap-5 items-center">
          <div>
            <p className="font-body text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Selected Heuristic</p>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full" style={{ background: HEURISTIC_COLORS.atc }} />
              <span className="font-heading text-xl font-bold text-foreground">ATC</span>
              {EXAMPLE_DECISION.switched && (
                <span className="badge-new">SWITCH</span>
              )}
            </div>
          </div>
          <div className="h-10 w-px bg-border/50 hidden md:block" />
          <div>
            <p className="font-body text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Confidence</p>
            <span className="font-heading text-xl font-bold text-primary">{(EXAMPLE_DECISION.confidence * 100).toFixed(0)}%</span>
          </div>
          <div className="h-10 w-px bg-border/50 hidden md:block" />
          <div>
            <p className="font-body text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Reason</p>
            <span className="font-mono text-sm text-foreground">{EXAMPLE_DECISION.reason}</span>
          </div>
          <div className="flex gap-2 ml-auto flex-wrap">
            {['all', 'plain', 'attribution', 'dtpath'].map(l => (
              <button
                key={l}
                onClick={() => setLevel(l)}
                className={`px-3 py-1.5 rounded-full font-body text-xs font-semibold transition-all ${
                  level === l ? 'bg-primary text-white' : 'bg-muted text-muted-foreground hover:bg-primary/10'
                }`}
              >
                {l === 'all' ? 'All Levels' : l === 'plain' ? 'Level 1: Plain English' : l === 'attribution' ? 'Level 2: Attribution' : 'Level 3: DT Path'}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-5">

          {/* LEVEL 1: Plain English */}
          {(level === 'all' || level === 'plain') && (
            <div className="rounded-2xl border border-blue-200 bg-blue-50/60 p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center">
                  <Brain size={16} className="text-blue-700" />
                </div>
                <div>
                  <span className="font-body text-[10px] font-bold text-blue-700 uppercase tracking-wider">Level 1</span>
                  <p className="font-heading text-base font-semibold text-foreground">Plain English Explanation</p>
                </div>
              </div>
              <blockquote className="font-body text-base text-foreground leading-relaxed bg-white rounded-xl p-4 border border-blue-100">
                "{EXAMPLE_DECISION.plainEnglish}"
              </blockquote>
            </div>
          )}

          {/* LEVEL 2: Feature attribution */}
          {(level === 'all' || level === 'attribution') && (
            <div className="rounded-2xl border border-purple-200 bg-purple-50/40 p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-8 h-8 rounded-full bg-purple-100 flex items-center justify-center">
                  <Zap size={16} className="text-purple-700" />
                </div>
                <div className="flex-1">
                  <span className="font-body text-[10px] font-bold text-purple-700 uppercase tracking-wider">Level 2</span>
                  <p className="font-heading text-base font-semibold text-foreground">Feature Attribution (Top 5)</p>
                </div>
                <span className="text-[10px] font-bold px-2.5 py-1 rounded-full bg-purple-100 text-purple-700">[Lundberg &amp; Lee, 2017]</span>
              </div>
              <p className="font-body text-xs text-purple-700 italic mb-4">
                Feature attribution follows the SHAP (SHapley Additive exPlanations) framework:{' '}
                Lundberg, S.M. &amp; Lee, S.I. (2017). A unified approach to interpreting model predictions.
                NeurIPS 2017, 30, 4765-4774. Model importances serve as SHAP-style attribution.
              </p>

              <div className="bg-white rounded-xl p-4 border border-purple-100">
                <div className="flex items-center gap-3 mb-3 text-[10px] font-bold text-muted-foreground uppercase tracking-wider">
                  <div className="w-40">Feature</div>
                  <div className="flex-1">Importance (model)</div>
                  <div className="w-16 text-right">Imp.</div>
                  <div className="w-14 text-right text-primary">Value</div>
                </div>
                <div className="space-y-3">
                  {EXAMPLE_DECISION.topFeatures.map((f, i) => (
                    <FeatureBar key={i} {...f} maxImportance={maxImportance} />
                  ))}
                </div>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2">
                {Object.entries(EXAMPLE_DECISION.probabilities).map(([h, p]) => (
                  <div key={h} className={`text-center px-3 py-2 rounded-xl border ${
                    h === EXAMPLE_DECISION.heuristic
                      ? 'bg-primary/10 border-primary/30'
                      : 'bg-white border-border/30'
                  }`}>
                    <p className="font-mono text-[10px] font-bold text-foreground">{h}</p>
                    <p className={`font-mono text-sm font-bold ${h === EXAMPLE_DECISION.heuristic ? 'text-primary' : 'text-muted-foreground'}`}>
                      {(p * 100).toFixed(0)}%
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* LEVEL 3: DT path */}
          {(level === 'all' || level === 'dtpath') && (
            <div className="rounded-2xl border border-green-200 bg-green-50/40 p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-8 h-8 rounded-full bg-green-100 flex items-center justify-center">
                  <Shield size={16} className="text-green-700" />
                </div>
                <div>
                  <span className="font-body text-[10px] font-bold text-green-700 uppercase tracking-wider">Level 3</span>
                  <p className="font-heading text-base font-semibold text-foreground">Decision Tree Path (Glass-box)</p>
                </div>
              </div>
              <div className="bg-white rounded-xl p-4 border border-green-100 font-mono">
                <DtPathViz path={EXAMPLE_DECISION.dtPath} leaf={EXAMPLE_DECISION.dtLeaf} />
              </div>
              <p className="font-body text-xs text-green-700 mt-3 italic">
                The decision tree provides a fully auditable path from input features to heuristic choice.
                This is the same model structure exported as dt_structure.json and visualized in the training artifacts.
              </p>
            </div>
          )}
        </div>
      </section>

      {/* ── FEATURE EXPLORER ──────────────────────────────────────── */}
      <section ref={r2} className={`bg-foreground/[0.02] border-y border-border/40 py-16 reveal ${v2 ? 'visible' : ''}`}>
        <div className="max-w-4xl mx-auto px-6">
          <div className="mb-8">
            <div className="inline-block px-4 py-1.5 rounded-full bg-violet-100 text-violet-700 text-sm font-bold mb-3">22 Features</div>
            <h2 className="font-heading text-3xl font-bold text-foreground mb-2">Interactive Feature Explorer</h2>
            <p className="font-body text-muted-foreground max-w-2xl">
              Browse all 22 system-state features used by the ML classifier. Features are loaded from
              the backend's <code className="font-mono text-xs bg-slate-100 px-1 rounded">feature_names.json</code> artifact.
            </p>
          </div>
          <FeatureExplorer />
        </div>
      </section>

      {/* ── HEURISTIC INFO ────────────────────────────────────────── */}
      <section ref={r3} className={`max-w-5xl mx-auto px-6 py-16 reveal ${v3 ? 'visible' : ''}`}>
        <div className="mb-8">
          <div className="inline-block px-4 py-1.5 rounded-full bg-primary/10 text-primary text-sm font-bold mb-3">Heuristic Library</div>
          <h2 className="font-heading text-3xl font-bold text-foreground mb-2">Dispatch Rules — When &amp; Why</h2>
          <p className="font-body text-muted-foreground max-w-2xl">
            Click any heuristic to see when the ML is likely to select it.
          </p>
        </div>
        <HeuristicCards />
      </section>
    </div>
  );
}
