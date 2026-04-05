import { WarehouseSimulator } from './src/simulation/engine.js';

const seeds = [42, 99, 123, 456, 789, 1001, 5000, 9999, 31337, 77777];
const methods = ['FIFO','EDD','CR','WSPT','ATC'];

let wins = 0;
let tardWins = 0;
let slaWins = 0;

console.log('\n=== HYBRID vs ALL BASELINES (10 seeds) ===\n');
console.log('Seed  | WSPT   | ATC    | HYBRID | Beat All? | SLA_WSPT | SLA_H  | SLA_Win?');
console.log('------|--------|--------|--------|-----------|----------|--------|--------');

for (const seed of seeds) {
  const results = {};
  for (const m of [...methods, 'HYBRID']) {
    results[m] = new WarehouseSimulator(m, seed).runToEnd(600);
  }

  const bestTard = Math.min(...methods.map(m => results[m].totalTardiness));
  const bestSla  = Math.min(...methods.map(m => results[m].slaBreachRate));

  const tardWin = results['HYBRID'].totalTardiness <= bestTard;
  const slaWin  = results['HYBRID'].slaBreachRate  <= bestSla;

  if (tardWin) tardWins++;
  if (slaWin)  slaWins++;
  if (tardWin && slaWin) wins++;

  const h = results['HYBRID'];
  const w = results['WSPT'];
  const a = results['ATC'];

  console.log(
    String(seed).padEnd(5) + ' | ' +
    w.totalTardiness.toFixed(0).padStart(6) + ' | ' +
    a.totalTardiness.toFixed(0).padStart(6) + ' | ' +
    h.totalTardiness.toFixed(0).padStart(6) + ' | ' +
    (tardWin ? '  ✓ YES   ' : '  ✗ NO    ') + ' | ' +
    (w.slaBreachRate*100).toFixed(1).padStart(8)+'%' + ' | ' +
    (h.slaBreachRate*100).toFixed(1).padStart(6)+'%' + ' | ' +
    (slaWin ? '✓' : '✗')
  );
}

console.log('\n=== SUMMARY ===');
console.log('Tardy wins (HYBRID tardiness ≤ best baseline): ' + tardWins + '/' + seeds.length);
console.log('SLA wins   (HYBRID SLA ≤ best baseline):       ' + slaWins  + '/' + seeds.length);
console.log('Full wins  (both metrics):                     ' + wins     + '/' + seeds.length);
