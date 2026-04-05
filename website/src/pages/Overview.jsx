import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Activity, Clock, FileText, Blocks } from 'lucide-react';

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

function Counter({ value, suffix = '', duration = 1600 }) {
  const [count, setCount] = useState(0);
  const [ref, vis] = useReveal(0.3);
  const started = useRef(false);

  useEffect(() => {
    if (!vis || started.current) return;
    started.current = true;
    const start = performance.now();
    const target = parseFloat(value);
    const tick = (now) => {
      const p = Math.min((now - start) / duration, 1);
      const ease = 1 - Math.pow(1 - p, 3);
      setCount(+(target * ease).toFixed(1));
      if (p < 1) requestAnimationFrame(tick);
      else setCount(target);
    };
    requestAnimationFrame(tick);
  }, [vis, value, duration]);

  return (
    <span ref={ref}>
      {typeof value === 'string' && value.includes('%')
        ? count.toFixed(1) + '%'
        : count % 1 === 0 ? count.toFixed(0) + suffix : count.toFixed(1) + suffix
      }
    </span>
  );
}

export default function Overview() {
  const [absRef, absVis] = useReveal();

  return (
    <div className="overflow-x-hidden">
      {/* Ambient blobs */}
      <div className="blob-bg bg-primary/15 w-[60vw] h-[60vh] shape-organic-1 top-[-10vh] left-[-10vw]" />
      <div className="blob-bg bg-accent/40 w-[50vw] h-[50vh] shape-organic-2 top-[20vh] right-[-5vw] animate-[float-blob-alt_18s_ease-in-out_infinite_alternate]" />

      {/* Hero */}
      <section className="relative min-h-[85vh] flex items-center justify-center px-6">
        <div className="relative z-10 max-w-4xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 px-6 py-2 rounded-full bg-white/70 backdrop-blur-sm border border-border/60 text-primary font-body text-sm font-semibold mb-10 shadow-soft">
            <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
            Machine Learning · Dispatch Scheduling
          </div>

          <h1 className="font-heading text-6xl md:text-8xl font-semibold leading-[1.05] tracking-tight text-foreground mb-8 text-balance">
            Disruption-Aware<br />
            <span className="italic text-primary font-light">Scheduling</span>
          </h1>

          <p className="font-body text-lg md:text-xl text-muted-foreground max-w-2xl mx-auto mb-14 leading-relaxed text-balance">
            A supervised ML framework that dynamically selects the optimal dispatch heuristic from six candidates, adapting in real-time to warehouse disruptions across 22 system-state features.
          </p>

          <div className="flex flex-col sm:flex-row gap-4 justify-center items-center">
            <Link
              to="/simulation"
              className="flex items-center gap-2 font-body font-bold text-base text-white bg-primary px-10 py-4 rounded-full shadow-soft hover:shadow-[0_6px_24px_-4px_rgba(30,58,138,0.30)] hover:-translate-y-1 active:translate-y-0 active:scale-95 transition-all duration-300 group"
            >
              Live Simulation
              <ArrowRight size={18} className="group-hover:translate-x-1 transition-transform duration-300" />
            </Link>
            <Link
              to="/baselines"
              className="flex items-center gap-2 font-body font-bold text-base text-secondary border-2 border-secondary px-10 py-4 rounded-full hover:bg-secondary/5 hover:-translate-y-1 active:translate-y-0 active:scale-95 transition-all duration-300"
            >
              Methodology
            </Link>
          </div>
        </div>
      </section>

      {/* Stats strip */}
      <section className="py-20 relative z-10">
        <div className="max-w-6xl mx-auto px-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6 md:gap-8">
            {[
              { val: '93.7', unit: '%', desc: 'Tardiness Reduction', shape: 'shape-organic-1' },
              { val: '4.8',  unit: '%', desc: 'SLA Breach Rate',     shape: 'shape-organic-2' },
              { val: '300',  unit: '',  desc: 'Test Scenarios',      shape: 'shape-organic-3' },
              { val: '22',   unit: '',  desc: 'Feature Signals',     shape: 'shape-organic-4' },
            ].map((stat, i) => (
              <div
                key={i}
                className={`p-8 bg-white/70 backdrop-blur border border-border/50 ${stat.shape} flex flex-col items-center justify-center text-center shadow-soft hover:-translate-y-2 hover:shadow-float transition-all duration-500 group`}
              >
                <div className="font-heading text-5xl md:text-6xl text-primary mb-2 group-hover:scale-110 transition-transform duration-500">
                  <Counter value={stat.val} suffix={stat.unit} />
                </div>
                <div className="font-body font-bold text-sm text-muted-foreground uppercase tracking-wider">
                  {stat.desc}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Problem & Solution */}
      <section className="py-32 relative z-10">
        <div className="max-w-5xl mx-auto px-6 relative" ref={absRef}>
          <div className={`reveal ${absVis ? 'visible' : ''} bg-white rounded-[3rem] rounded-tl-[5rem] p-10 md:p-16 border border-border/50 shadow-soft relative overflow-hidden`}>
            <div className="absolute top-0 right-0 w-64 h-64 bg-accent/40 shape-organic-2 blur-3xl rounded-full translate-x-1/2 -translate-y-1/2" />

            <div className="max-w-3xl relative z-10">
              <div className="w-16 h-16 rounded-[1.5rem] bg-primary/10 flex items-center justify-center text-primary mb-8">
                <Blocks size={32} strokeWidth={1.5} />
              </div>
              <h2 className="font-heading text-4xl md:text-5xl text-foreground mb-8 leading-tight">
                Finding the optimal dispatch rule for every moment of disruption.
              </h2>

              <div className="font-body text-lg text-foreground/80 leading-relaxed space-y-6">
                <p>
                  Modern fulfillment centers are dynamic, stochastic environments. Machine breakdowns, order surges, and priority escalations render static dispatch rules fundamentally inadequate — a single heuristic tuned for normal conditions degrades rapidly under disruption.
                </p>
                <p>
                  <strong>DAHS</strong> (Disruption-Aware Hybrid Scheduler) addresses the Algorithm Selection Problem directly. An XGBoost classifier observes 22 real-time system features — including four novel disruption signals — and selects the most appropriate heuristic from six candidates at every dispatch event. Evaluated across 300 held-out scenarios, DAHS achieves a total tardiness of <strong>1,617 minutes</strong>, a 93.7% reduction against the best static rule (FIFO: 25,633 min), with SLA breach rate of just <strong>4.8%</strong>.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
