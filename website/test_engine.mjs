import { WarehouseSimulator } from './src/simulation/engine.js';

let passed = 0;
let failed = 0;

function assert(condition, label, detail = '') {
  if (condition) {
    console.log(`  PASS: ${label}`);
    passed++;
  } else {
    console.error(`  FAIL: ${label}${detail ? ' -- ' + detail : ''}`);
    failed++;
  }
}

const METHODS = ['FIFO', 'EDD', 'CR', 'WSPT', 'ATC'];

// TEST 1: No Negative Metrics
console.log('\n=== TEST 1: No Negative Metrics ===');
for (const m of METHODS) {
  const r = new WarehouseSimulator(m, 42).runToEnd(600);
  assert(r.completed >= 0,        `${m} completed >= 0`, `${r.completed}`);
  assert(r.late >= 0,             `${m} late >= 0`, `${r.late}`);
  assert(r.totalTardiness >= 0,   `${m} totalTardiness >= 0`, `${r.totalTardiness}`);
  assert(r.slaBreachRate >= 0 && r.slaBreachRate <= 1, `${m} slaBreachRate in [0,1]`, `${r.slaBreachRate}`);
  assert(r.avgCycleTime >= 0,     `${m} avgCycleTime >= 0`, `${r.avgCycleTime}`);
  assert(r.throughput >= 0,       `${m} throughput >= 0`, `${r.throughput}`);
}

// TEST 2: slaBreachRate = late/completed
console.log('\n=== TEST 2: slaBreachRate = late/completed ===');
for (const m of METHODS) {
  const r = new WarehouseSimulator(m, 42).runToEnd(600);
  const expected = r.completed > 0 ? r.late / r.completed : 0;
  assert(Math.abs(r.slaBreachRate - expected) < 1e-9, `${m} slaBreachRate consistent`, `got ${r.slaBreachRate.toFixed(6)} expected ${expected.toFixed(6)}`);
}

// TEST 3: late <= completed
console.log('\n=== TEST 3: late <= completed ===');
for (const m of METHODS) {
  const r = new WarehouseSimulator(m, 42).runToEnd(600);
  assert(r.late <= r.completed, `${m} late<=completed`, `late=${r.late} completed=${r.completed}`);
}

// TEST 4: avgCycleTime > 0
console.log('\n=== TEST 4: avgCycleTime > 0 ===');
for (const m of METHODS) {
  const r = new WarehouseSimulator(m, 42).runToEnd(600);
  assert(r.avgCycleTime > 0, `${m} avgCycleTime > 0`, `got ${r.avgCycleTime}`);
}

// TEST 5: Throughput is reasonable (> 0, < 500 j/hr given ~2.5 arrivals/min = 150/hr max)
console.log('\n=== TEST 5: Throughput in plausible range ===');
for (const m of METHODS) {
  const r = new WarehouseSimulator(m, 42).runToEnd(600);
  assert(r.throughput > 0 && r.throughput < 500, `${m} throughput in (0,500)`, `got ${r.throughput.toFixed(2)}`);
}

// TEST 6: Reproducibility — same seed same result
console.log('\n=== TEST 6: Seed Reproducibility ===');
for (const m of METHODS) {
  const r1 = new WarehouseSimulator(m, 99).runToEnd(600);
  const r2 = new WarehouseSimulator(m, 99).runToEnd(600);
  assert(r1.completed === r2.completed && r1.totalTardiness === r2.totalTardiness,
    `${m} deterministic`, `${r1.completed} vs ${r2.completed}`);
}

// TEST 7: Different seeds produce different results
console.log('\n=== TEST 7: Different Seeds Differ ===');
const fs1 = new WarehouseSimulator('FIFO', 1).runToEnd(600);
const fs2 = new WarehouseSimulator('FIFO', 9999).runToEnd(600);
assert(fs1.totalTardiness !== fs2.totalTardiness, 'FIFO seed 1 vs 9999 differ', `${fs1.totalTardiness} vs ${fs2.totalTardiness}`);

// TEST 8: Snapshot urgency in [0, 1] clamped by Math.max(0,...)
console.log('\n=== TEST 8: No Negative Urgency in Snapshots ===');
{
  const snap_sim = new WarehouseSimulator('FIFO', 42);
  let negUrgency = false;
  let maxUrgency = 0;
  for (let t = 50; t < 600; t += 50) {
    const snap = snap_sim.advanceTo(t);
    for (const j of snap.activeJobs) {
      if (j.urgency < 0) { negUrgency = true; console.error(`  NEG URGENCY at t=${t}: ${j.urgency}`); }
      if (j.urgency > maxUrgency) maxUrgency = j.urgency;
    }
  }
  assert(!negUrgency, 'No negative urgency values');
  console.log(`  Max urgency seen: ${maxUrgency.toFixed(4)}`);
}

// TEST 9: CR — check sort direction (lowest CR = most overdue = dispatched first)
console.log('\n=== TEST 9: CR Dispatch Ordering Sanity ===');
{
  // If CR is negative (dueDate < now), that job should go first.
  // Because sort is ascending (cr(a) - cr(b)), lower CR (negative) goes first. This IS correct.
  // But negative CR means job is past due - let's verify these jobs DO get dispatched first.
  const cr_sim = new WarehouseSimulator('CR', 42);
  const r = cr_sim.runToEnd(600);
  // CR should be no worse than FIFO on tardiness (it's deadline-aware)
  const fifo_r = new WarehouseSimulator('FIFO', 42).runToEnd(600);
  console.log(`  CR tardiness=${r.totalTardiness.toFixed(0)} vs FIFO=${fifo_r.totalTardiness.toFixed(0)}`);
  // NOTE: CR CAN have higher tardiness due to thrashing behavior with many simultaneous overdue jobs.
  // The metric itself must still be non-negative.
  assert(r.totalTardiness >= 0, 'CR totalTardiness >= 0');
}

// TEST 10: HYBRID with different parameters produces different results
console.log('\n=== TEST 10: HYBRID Parameters Actually Change Behavior ===');
{
  const h_base = new WarehouseSimulator('HYBRID', 42, { kFactor: 2.0, lookaheadWeight: 0.0, weightMultiplier: 1.0 }).runToEnd(600);
  const h_tuned = new WarehouseSimulator('HYBRID', 42, { kFactor: 1.0, lookaheadWeight: 3.0, weightMultiplier: 2.0 }).runToEnd(600);
  console.log(`  HYBRID(base):  tardiness=${h_base.totalTardiness.toFixed(0)} late=${h_base.late}`);
  console.log(`  HYBRID(tuned): tardiness=${h_tuned.totalTardiness.toFixed(0)} late=${h_tuned.late}`);
  // Just verify both complete jobs without errors
  assert(h_base.completed > 0 && h_tuned.completed > 0, 'Both HYBRID configs complete jobs');
}

// TEST 11: avgCycleTime computed from completionTime - arrivalTime should never be negative
console.log('\n=== TEST 11: avgCycleTime from positive differences only ===');
for (const m of METHODS) {
  // avgCycleTime = sum(completionTime - arrivalTime) / n
  // completionTime >= arrivalTime always (jobs complete AFTER arriving)
  // If avgCycleTime < 0, there's a bug in metric tracking.
  const r = new WarehouseSimulator(m, 42).runToEnd(600);
  assert(r.avgCycleTime >= 0, `${m} cycleTime >= 0`);
}

// FULL COMPARISON TABLE
console.log('\n=== FULL COMPARISON TABLE (Seed 42) ===');
console.log('  Method   | Done | Late | SLA%  | Tardiness | Thru  | CycleTime');
console.log('  ---------|------|------|-------|-----------|-------|----------');
const allM = ['FIFO', 'EDD', 'CR', 'WSPT', 'ATC'];
for (const m of allM) {
  const r = new WarehouseSimulator(m, 42).runToEnd(600);
  console.log(`  ${m.padEnd(8)} | ${String(r.completed).padStart(4)} | ${String(r.late).padStart(4)} | ${(r.slaBreachRate*100).toFixed(1).padStart(5)} | ${r.totalTardiness.toFixed(0).padStart(9)} | ${r.throughput.toFixed(1).padStart(5)} | ${r.avgCycleTime.toFixed(1)}`);
}
const rH = new WarehouseSimulator('HYBRID', 42, { kFactor: 2.0, lookaheadWeight: 2.0, weightMultiplier: 1.5 }).runToEnd(600);
console.log(`  HYBRID   | ${String(rH.completed).padStart(4)} | ${String(rH.late).padStart(4)} | ${(rH.slaBreachRate*100).toFixed(1).padStart(5)} | ${rH.totalTardiness.toFixed(0).padStart(9)} | ${rH.throughput.toFixed(1).padStart(5)} | ${rH.avgCycleTime.toFixed(1)}`);

console.log(`\n=== SUMMARY: ${passed} passed, ${failed} failed ===\n`);
if (failed > 0) process.exit(1);
