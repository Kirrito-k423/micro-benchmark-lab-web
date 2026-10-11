export const median = values => {
  const xs = [...values].sort((a, b) => a - b);
  return (xs[Math.floor((xs.length - 1) / 2)] + xs[Math.ceil((xs.length - 1) / 2)]) / 2;
};
export const ringKind = row => row.requestedWorkingSet < 128 * 2 ** 20 ? 'small' : String(row.requestedWorkingSet);
export function measurementGroups(db, state) {
  const map = new Map();
  for (const r of db.rows) {
    if (r.control || r.kind !== state.kind || state.round !== 'all' && r.round !== Number(state.round) ||
        state.policy !== 'all' && r.allocation !== state.policy) continue;
    if (r.kind === 'latency') {
      if (r.api !== state.api || r.direction !== state.direction || r.windows !== Number(state.windows)) continue;
    } else if (ringKind(r) !== state.ring || r.tileBytes !== Number(state.tile) || state.mode !== 'all' && r.mode !== state.mode) continue;
    const key = `${r.kind}/${r.caseId}/${r.allocation}`;
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(r);
  }
  return [...map.values()].map(members => {
    members.sort((a, b) => a.round - b.round);
    const r = members[0], p50 = median(members.map(r => r.p50)), p95 = median(members.map(r => r.p95));
    // Each duplex direction uses the same complete kernel interval, including in the combined view.
    return { ...r, members, p50, p95, x: r.kind === 'latency' ? r.bytes : r.cores,
      gbps: r.movedBytes / p50 / 1000, readGbps: (r.readBytes || 0) / p50 / 1000,
      writeGbps: (r.writeBytes || 0) / p50 / 1000 };
  }).sort((a, b) => a.x - b.x || a.allocation.localeCompare(b.allocation) || a.caseId - b.caseId);
}
export function plotValue(row, state) {
  if (state.kind === 'latency') return state.stat === 'p95' ? row.p95 : row.p50;
  if (state.metric === 'us') return row.p50;
  return row[state.metric === 'read' ? 'readGbps' : state.metric === 'write' ? 'writeGbps' : 'gbps'] / 1000;
}
