import assert from 'node:assert/strict';
import { chartGeometry } from '../src/chart-geometry.js';

const rows = [[32, 0.02], [4096, 44], [4194304, 132.933]];
const scan = {
  grid: { left: 65, right: 22, top: 55, bottom: 75 },
  xAxis: { type: 'log', logBase: 2, min: 32, max: 4194304, name: '请求总字节 / B' },
  yAxis: { type: 'value', name: 'GB/s' },
  series: [{ type: 'line', data: rows }],
  dataZoom: [{ type: 'slider' }],
};
const original = structuredClone(scan);
const desktop = chartGeometry(600, scan);
assert.equal(desktop.height, 450, 'Default desktop ratio is 4:3');
assert.equal(desktop.option.xAxis.min, 32);
assert.equal(desktop.option.xAxis.max, 4194304);
assert.equal(desktop.option.xAxis.logBase, 2);
assert.equal(desktop.option.xAxis.axisLabel.showMinLabel, true);
assert.equal(desktop.option.xAxis.axisLabel.showMaxLabel, true);
assert.equal(desktop.option.yAxis.min, undefined, 'Keep the existing zero baseline');
assert.deepEqual(scan, original, 'Do not mutate authored data or axes');
assert.equal(desktop.option.series, undefined, 'Layout updates do not replace samples');

for (const width of [242, 330, 356, 600]) {
  const geometry = chartGeometry(width, scan);
  assert.ok(geometry.height - 130 >= 240, 'Reserve a readable plot on narrow screens');
  const dx = (width - 87) / geometry.option.xAxis.splitNumber;
  const dy = (geometry.height - 130) / geometry.option.yAxis.splitNumber;
  assert.ok(Math.max(dx, dy) / Math.min(dx, dy) < 1.65, 'Balance grid spacing on both axes');
}
const samples = chartGeometry(242, {
  grid: { left: 58, right: 12, top: 20, bottom: 22 },
  xAxis: { type: 'category', data: Array.from({ length: 12 }, (_, i) => i + 1) },
  yAxis: { type: 'value', scale: true, name: 'μs / 请求' },
}, true);
assert.equal(samples.option.xAxis.data.length, 12);
assert.equal(samples.option.yAxis.scale, true, 'Retain a focused sample domain');
assert.ok(samples.height >= 202);
const fixed = chartGeometry(356, {
  xAxis: { type: 'value', interval: 1, min: 0, max: 64 },
  yAxis: { type: 'value', min: -2, max: 2 },
});
assert.equal(fixed.option.xAxis.interval, 1);
assert.equal(fixed.option.xAxis.splitNumber, undefined);
assert.equal(fixed.option.yAxis.min, -2);
assert.equal(fixed.option.yAxis.max, 2);
console.log('CHART_LAYOUT_PASS desktop, narrow, samples, domains and raw-data preservation');
