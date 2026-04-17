import { useEffect, useRef, useState } from 'react';

/**
 * Intersection Observer hook — returns [ref, isVisible].
 * Once the element scrolls into view (past `threshold`), isVisible becomes true permanently.
 */
export default function useReveal(threshold = 0.15) {
  const ref = useRef(null);
  const [vis, setVis] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) setVis(true); },
      { threshold }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [threshold]);
  return [ref, vis];
}
