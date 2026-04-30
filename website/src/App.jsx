import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import Navbar from './components/Navbar.jsx';
import Footer from './components/Footer.jsx';
import BackToTop from './components/BackToTop.jsx';
import Landing from './pages/Landing.jsx';
import Methodology from './pages/Methodology.jsx';
import Simulation from './pages/Simulation.jsx';

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return null;
}

function AppShell() {
  const { pathname } = useLocation();
  const isSim = pathname === '/simulation';

  return (
    <>
      <div className="texture-paper" />
      <ScrollToTop />
      <Navbar />
      {isSim ? (
        <Routes>
          <Route path="/simulation" element={<Simulation />} />
        </Routes>
      ) : (
        <>
          <main className="relative z-10 pt-32 pb-24 text-foreground">
            <Routes>
              <Route path="/"            element={<Landing />} />
              <Route path="/methodology" element={<Methodology />} />
              <Route path="*"            element={<Navigate to="/" replace />} />
            </Routes>
          </main>
          <Footer />
          <BackToTop />
        </>
      )}
    </>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}
