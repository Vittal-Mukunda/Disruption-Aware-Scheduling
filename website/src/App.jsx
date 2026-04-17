import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom';
import Navbar from './components/Navbar.jsx';
import Footer from './components/Footer.jsx';
import BackToTop from './components/BackToTop.jsx';
import Overview from './pages/Overview.jsx';
import Methodology from './pages/Methodology.jsx';
import Simulation from './pages/Simulation.jsx';
import Interpretability from './pages/Interpretability.jsx';
import Results from './pages/Results.jsx';

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return null;
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="texture-paper" />
      <ScrollToTop />
      <Navbar />
      <main className="relative z-10 pt-32 pb-24 text-foreground">
        <Routes>
          <Route path="/"                  element={<Overview />} />
          <Route path="/methodology"       element={<Methodology />} />
          <Route path="/simulation"        element={<Simulation />} />
          <Route path="/interpretability"  element={<Interpretability />} />
          <Route path="/results"           element={<Results />} />
        </Routes>
      </main>
      <Footer />
      <BackToTop />
    </BrowserRouter>
  );
}
