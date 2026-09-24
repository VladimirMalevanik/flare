export type CapturePoint = { x: number; y: number };
export type CaptureSize = { width: number; height: number };
export type CaptureRect = CapturePoint & CaptureSize;

export const ORB_EDGE_PADDING = 12;
export const PANEL_EDGE_MARGIN = 16;
export const HOVER_INLINE_PADDING = 7;

function clamp(value: number, min: number, max: number) {
  if (max < min) return (min + max) / 2;
  return Math.min(Math.max(value, min), max);
}

export function clampOrbPosition(
  position: CapturePoint,
  orbSize: number,
  viewport: CaptureSize,
): CapturePoint {
  const edgeMargin = orbSize / 2 + ORB_EDGE_PADDING + HOVER_INLINE_PADDING;
  return {
    x: clamp(position.x, edgeMargin, viewport.width - edgeMargin),
    y: clamp(position.y, edgeMargin, viewport.height - edgeMargin),
  };
}

export function hoverRectFor(
  anchor: CapturePoint,
  orbSize: number,
  expandedWidth: number,
  viewportWidth: number,
): CaptureRect & { direction: "left" | "right" } {
  const width = Math.min(
    expandedWidth,
    Math.max(orbSize, viewportWidth - ORB_EDGE_PADDING * 2),
  );
  const rightX = anchor.x - orbSize / 2 - HOVER_INLINE_PADDING;
  const leftX = anchor.x + orbSize / 2 + HOVER_INLINE_PADDING - width;
  const rightFits = rightX + width <= viewportWidth - ORB_EDGE_PADDING;
  const leftFits = leftX >= ORB_EDGE_PADDING;
  const direction = rightFits || !leftFits ? "right" : "left";
  const idealX = direction === "right" ? rightX : leftX;

  return {
    x: clamp(idealX, ORB_EDGE_PADDING, Math.max(ORB_EDGE_PADDING, viewportWidth - ORB_EDGE_PADDING - width)),
    y: anchor.y - orbSize / 2 - HOVER_INLINE_PADDING,
    width,
    height: orbSize + HOVER_INLINE_PADDING * 2,
    direction,
  };
}

export function placeCapturePanel(
  anchor: CapturePoint,
  orbSize: number,
  requested: CaptureSize,
  viewport: CaptureSize,
): CaptureRect {
  const availableWidth = Math.max(0, viewport.width - PANEL_EDGE_MARGIN * 2);
  const availableHeight = Math.max(0, viewport.height - PANEL_EDGE_MARGIN * 2);
  const width = Math.min(Math.max(requested.width, orbSize), availableWidth);
  const height = Math.min(Math.max(requested.height, orbSize), availableHeight);

  return {
    x: clamp(
      anchor.x - width / 2,
      PANEL_EDGE_MARGIN,
      viewport.width - PANEL_EDGE_MARGIN - width,
    ),
    y: clamp(
      anchor.y - height / 2,
      PANEL_EDGE_MARGIN,
      viewport.height - PANEL_EDGE_MARGIN - height,
    ),
    width,
    height,
  };
}

export function captureTransformOrigin(anchor: CapturePoint, panel: CaptureRect): CapturePoint {
  return { x: anchor.x - panel.x, y: anchor.y - panel.y };
}
