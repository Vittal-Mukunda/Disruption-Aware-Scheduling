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
        <p className="font-heading text-2xl text-foreground mb-12 italic">
          Rooted in research, growing in efficiency.
        </p>
        <div className="flex flex-col md:flex-row justify-center items-center gap-4 md:gap-10 font-body text-[15px] text-muted-foreground w-full">
          <span>© 2026 DAHS Network</span>
          <span className="hidden md:inline w-1.5 h-1.5 bg-border rounded-full" />
          <span>Disruption-Aware Hybrid Scheduler</span>
          <span className="hidden md:inline w-1.5 h-1.5 bg-border rounded-full" />
          <a
            href="https://github.com/placeholder"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:text-primary/80 transition-colors duration-300 font-semibold relative after:absolute after:bottom-0 after:left-0 after:w-full after:h-px after:bg-primary/40 hover:after:bg-primary pb-1"
          >
            Explore Open Source
          </a>
        </div>
      </div>
    </footer>
  );
}
