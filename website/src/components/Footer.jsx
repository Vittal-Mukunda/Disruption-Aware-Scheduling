import React from 'react';
import { FlaskConical } from 'lucide-react';

export default function Footer() {
  return (
    <footer className="bg-muted/50 border-t border-border/50 pt-20 pb-12 mt-20">
      <div className="max-w-6xl mx-auto px-6 text-center">
        <div className="flex justify-center mb-8">
          <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center text-primary">
            <FlaskConical size={22} />
          </div>
        </div>
        <p className="font-heading text-2xl text-foreground mb-4 italic">
          Transparent, adaptive, and provably better.
        </p>
        <p className="font-body text-sm text-muted-foreground mb-10">
          DAHS 2.0 — Batch-wise ML Scheduling with Interpretability, Guardrails &amp; Statistical Rigour
        </p>
        <div className="flex flex-col md:flex-row justify-center items-center gap-4 md:gap-10 font-body text-[15px] text-muted-foreground w-full">
          <span>© 2026 DAHS Network</span>
          <span className="hidden md:inline w-1.5 h-1.5 bg-border rounded-full" />
          <span>Disruption-Aware Hybrid Scheduler v2.0</span>
          <span className="hidden md:inline w-1.5 h-1.5 bg-border rounded-full" />
          <a
            href="https://github.com/Vittal-Mukunda/Disruption-Aware-Scheduling"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:text-primary/80 transition-colors duration-300 font-semibold"
          >
            Explore Open Source
          </a>
        </div>
      </div>
    </footer>
  );
}
