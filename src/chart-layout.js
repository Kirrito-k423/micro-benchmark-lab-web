import * as echarts from 'echarts';
import { chartGeometry } from './chart-geometry.js';

export { getInstanceByDom } from 'echarts';

// Shared by every lab and A/B/C view, including point-sample charts.
export function init(dom, theme, options) {
  const chart = echarts.init(dom, theme, options);
  const setOption = chart.setOption.bind(chart);
  const resize = chart.resize.bind(chart);
  const dispose = chart.dispose.bind(chart);
  const compact = ['sample-chart', 'lab-samples', 'bw-balance'].includes(dom.id);
  let authored = {}, frame, observedWidth;
  dom.dataset.chartLayout = 'adaptive';

  const geometry = () => chartGeometry(dom.clientWidth, authored, compact);
  const size = layout => {
    dom.style.height = `${layout.height}px`;
    dom.dataset.chartRatio = (dom.clientWidth / layout.height).toFixed(3);
  };
  chart.setOption = (option, ...args) => {
    const notMerge = args[0] === true || args[0]?.notMerge;
    authored = notMerge ? { ...option } : { ...authored, ...option };
    const layout = geometry();
    size(layout);
    resize({ silent: true });
    return setOption({ ...option, ...layout.option }, ...args);
  };
  chart.resize = options => {
    if (chart.isDisposed() || !dom.isConnected || !dom.clientWidth) return;
    const layout = geometry();
    size(layout);
    resize(options);
    // Partial layout updates preserve selected legends and dataZoom state.
    setOption(layout.option, { silent: true });
  };
  const observer = new ResizeObserver(entries => {
    const width = entries[0]?.contentRect.width;
    if (width === observedWidth) return;
    observedWidth = width;
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => chart.resize());
  });
  observer.observe(dom);
  chart.dispose = () => {
    observer.disconnect();
    cancelAnimationFrame(frame);
    dispose();
  };
  return chart;
}
