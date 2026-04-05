import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom';
import Navbar from './components/Navbar.jsx';
import Footer from './components/Footer.jsx';
import BackToTop from './components/BackToTop.jsx';
import Overview from './pages/Overview.jsx';
import Baselines from './pages/Baselines.jsx';
import Simulation from './pages/Simulation.jsx';

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return null;
}

export default function App() {
  return (
    <BrowserRouter>
      {/* Organic Texture Overlay */}
      <div className="texture-paper"></div>
      
      <ScrollToTop />
      <Navbar />
      <main className="relative z-10 pt-32 pb-24 text-foreground">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/baselines" element={<Baselines />} />
          <Route path="/simulation" element={<Simulation />} />
        </Routes>
      </main>
      <Footer />
      <BackToTop />
    </BrowserRouter>
  );
}
