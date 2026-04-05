/**
 * Traces which sub-algorithm DAHS is picking at each dispatch,
 * and measures how often each is chosen.
 */
import { WarehouseSimulator } from './src/simulation/engine.js';

class TracingSim extends WarehouseSimulator {
  constructor(seed) {
    super('HYBRID', seed);
    this._algoPicks = { WSPT: 0, ATC: 0, CR: 0, EDD: 0 };
  }
  _dispatch(zoneId) {
    super._dispatch(zoneId);
    if (this._lastSelectedAlgo) {
      this._algoPicks[this._lastSelectedAlgo] = (this._algoPicks[this._lastSelectedAlgo]||0) + 1;
    }
  }
}

const seed = 42;
const sim = new TracingSim(seed);
sim.runToEnd(600);

const total = Object.values(sim._algoPicks).reduce((a,b)=>a+b,0);
console.log('\n=== DAHS Algorithm Selection Distribution (seed='+seed+') ===');
for (const [algo, count] of Object.entries(sim._algoPicks)) {
  const pct = total > 0 ? (count/total*100).toFixed(1) : '0.0';
  console.log('  ' + algo.padEnd(6) + ': ' + count + ' dispatches (' + pct + '%)');
}
console.log('  Total dispatches: ' + total);
console.log('\n  HYBRID tardiness: ' + sim.metrics.totalTardiness.toFixed(0));
const wspt = new WarehouseSimulator('WSPT', seed).runToEnd(600);
console.log('  WSPT  tardiness: ' + wspt.totalTardiness.toFixed(0));
