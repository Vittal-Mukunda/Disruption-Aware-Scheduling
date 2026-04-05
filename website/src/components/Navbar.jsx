import React from 'react';
import { NavLink } from 'react-router-dom';
import { FlaskConical } from 'lucide-react';

const NAV_LINKS = [
  { to: '/',          label: 'Overview'    },
  { to: '/baselines', label: 'Methodology' },
  { to: '/simulation',label: 'Simulation'  },
];

export default function Navbar() {
  return (
    <div className="fixed top-6 left-0 right-0 z-50 flex justify-center px-4">
      <nav className="bg-white/80 backdrop-blur-md rounded-full px-4 py-2 border border-border/60 shadow-soft flex items-center gap-8 hover:bg-white/95 transition-all duration-500">
        <NavLink to="/" className="flex items-center gap-2 group ml-2">
          <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center group-hover:bg-primary transition-colors duration-500">
            <FlaskConical size={18} className="text-primary group-hover:text-white transition-colors duration-500" />
          </div>
          <span className="font-heading font-semibold text-xl pt-1 text-foreground">DAHS</span>
        </NavLink>

        <ul className="hidden md:flex items-center gap-2 font-body font-medium text-[15px]">
          {NAV_LINKS.map(({ to, label }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  `px-5 py-2.5 rounded-full transition-all duration-300 ${
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
            href="https://github.com/placeholder"
            target="_blank"
            rel="noopener noreferrer"
            className="px-6 py-2.5 rounded-full bg-primary text-white font-body font-semibold text-[15px] shadow-soft hover:shadow-[0_6px_24px_-4px_rgba(30,58,138,0.30)] hover:-translate-y-0.5 active:translate-y-0 transition-all duration-300 ease-out focus-visible:ring-2 focus-visible:ring-primary/30 focus-visible:ring-offset-2"
          >
            Repository
          </a>
        </div>
      </nav>
    </div>
  );
}
