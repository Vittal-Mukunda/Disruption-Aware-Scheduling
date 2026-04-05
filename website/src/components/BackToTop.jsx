import React, { useState, useEffect } from 'react';
import { ArrowUp } from 'lucide-react';

export default function BackToTop() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const onScroll = () => setVisible(window.scrollY > 300);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <button
      onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
      aria-label="Back to top"
      className={`fixed bottom-8 right-8 w-14 h-14 bg-white/70 backdrop-blur-md rounded-full border border-border/50 flex flex-col items-center justify-center text-primary shadow-float z-50 transition-all duration-500 ease-out hover:scale-105 hover:bg-white hover:text-foreground active:scale-95 focus-visible:ring-2 focus-visible:ring-primary/30 ${visible ? 'opacity-100 translate-y-0 pointer-events-auto' : 'opacity-0 translate-y-8 pointer-events-none'}`}
    >
      <ArrowUp size={24} strokeWidth={2} />
    </button>
  );
}
