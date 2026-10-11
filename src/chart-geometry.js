const first = value => Array.isArray(value) ? value[0] : value;
const px = (value, fallback) => typeof value === 'number' ? value : fallback;
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

// Geometry and tick density only. Keep data, domains, units and log bases intact.
export function chartGeometry(width, option = {}, compact = false) {
  const grid = first(option.grid) || {};
  const left = px(grid.left, 60), right = px(grid.right, 20);
  const top = px(grid.top, 35), bottom = px(grid.bottom, 35);
  const plotWidth = Math.max(1, width - left - right);
  const minPlotHeight = compact ? 160 : 240;
  const height = Math.ceil(Math.max(width * 3 / 4, top + bottom + minPlotHeight));
  const plotHeight = height - top - bottom;
  // Similar pixel spacing on both axes, rather than equal unlike physical units.
  const xSplits = clamp(Math.round(plotWidth / 85), 2, 10);
  const ySplits = clamp(Math.round(plotHeight / 85), 2, 10);
  const axis = (original, splits, horizontal) => {
    if (!original) return undefined;
    const adapt = value => ({
      ...value,
      ...(['value', 'log'].includes(value.type || 'value') && !value.interval
        ? { splitNumber: splits } : {}),
      axisLabel: {
        ...value.axisLabel, hideOverlap: true,
        ...(['value', 'log'].includes(value.type || 'value') ? {
          showMinLabel: value.axisLabel?.showMinLabel ?? true,
          showMaxLabel: value.axisLabel?.showMaxLabel ?? true,
        } : {}),
      },
      ...(horizontal && value.name ? {
        nameLocation: 'middle', nameGap: value.nameGap ?? 30,
      } : {}),
    });
    return Array.isArray(original) ? original.map(adapt) : adapt(original);
  };
  const zoom = (Array.isArray(option.dataZoom) ? option.dataZoom : [option.dataZoom])
    .some(value => value?.type === 'slider');
  return {
    height,
    option: {
      grid: {
        ...grid,
        outerBounds: { left: 8, right: 8, top: 4, bottom: zoom ? 32 : 4 },
        outerBoundsContain: 'all',
      },
      ...(option.xAxis ? { xAxis: axis(option.xAxis, xSplits, true) } : {}),
      ...(option.yAxis ? { yAxis: axis(option.yAxis, ySplits, false) } : {}),
    },
  };
}
