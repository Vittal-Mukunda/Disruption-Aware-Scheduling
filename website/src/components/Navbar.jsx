import React, { useState } from 'react';
import { NavLink } from 'react-router-dom';
import { FlaskConical, Menu, X } from 'lucide-react';

const NAV_LINKS = [
  { to: '/',            label: 'Home'        },
  { to: '/methodology', label: 'Methodology' },
  { to: '/simulation',  label: 'Simulation'  },
];

export default function Navbar() {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="fixed top-6 left-0 right-0 z-50 flex justify-center px-4">
      <nav className="bg-white/80 backdrop-blur-md rounded-full px-4 py-2 border border-border/60 shadow-soft flex items-center gap-6 hover:bg-white/95 transition-all duration-500 relative">
        <NavLink to="/" className="flex items-center gap-2 group ml-2">
          <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center group-hover:bg-primary transition-colors duration-500">
            <FlaskConical size={18} className="text-primary group-hover:text-white transition-colors duration-500" />
          </div>
          <span className="font-heading font-semibold text-xl pt-1 text-foreground">
            DAHS <span className="text-primary text-sm font-bold">2.0</span>
          </span>
        </NavLink>

        {/* Desktop nav */}
        <ul className="hidden md:flex items-center gap-1 font-body font-medium text-[14px]">
          {NAV_LINKS.map(({ to, label }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  `px-4 py-2 rounded-full transition-all duration-300 ${
                    isActive
                      ? 'bg-primary/10 text-primary font-semibold'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                  }`
                }
              >
                {label}
              </NavLink>
            </li>
          ))}
        </ul>

        <div className="hidden md:block">
          <a
            href="https://github.com/Vittal-Mukunda/Disruption-Aware-Scheduling"
            target="_blank"
            rel="noopener noreferrer"
            className="px-5 py-2 rounded-full bg-primary text-white font-body font-semibold text-[13px] shadow-soft hover:shadow-glow hover:-translate-y-0.5 active:translate-y-0 transition-all duration-300"
          >
            GitHub
          </a>
        </div>

        {/* Mobile hamburger */}
        <button
          className="md:hidden p-2 rounded-full hover:bg-muted transition-colors"
          onClick={() => setMobileOpen(o => !o)}
          aria-label="Toggle navigation"
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </nav>

      {/* Mobile dropdown */}
      {mobileOpen && (
        <div className="md:hidden fixed top-[5.5rem] left-4 right-4 bg-white/95 backdrop-blur-md rounded-2xl border border-border/60 shadow-soft p-4 z-50 animate-in fade-in slide-in-from-top-2">
          <ul className="flex flex-col gap-1 font-body font-medium text-[14px]">
            {NAV_LINKS.map(({ to, label }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={to === '/'}
                  onClick={() => setMobileOpen(false)}
                  className={({ isActive }) =>
                    `block px-4 py-3 rounded-xl transition-all duration-300 ${
                      isActive
                        ? 'bg-primary/10 text-primary font-semibold'
                        : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                    }`
                  }
                >
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
          <div className="mt-3 pt-3 border-t border-border/40">
            <a
              href="https://github.com/Vittal-Mukunda/Disruption-Aware-Scheduling"
              target="_blank"
              rel="noopener noreferrer"
              className="block text-center px-5 py-2.5 rounded-full bg-primary text-white font-body font-semibold text-[13px] shadow-soft"
            >
              GitHub
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
