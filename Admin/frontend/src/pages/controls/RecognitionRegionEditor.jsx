import React, { useEffect, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { Alert, Button, Segmented, Space, Typography, theme } from 'antd';

const { Text } = Typography;

const FULL_FRAME_REGION = '0,0,1,0,1,1,0,1';
const STAGE_ASPECT_RATIO = '16 / 9';
const RECT_OPPOSITE_INDEX = [2, 3, 0, 1];

function clamp01(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  if (number < 0) return 0;
  if (number > 1) return 1;
  return number;
}

function formatCoordinate(value) {
  const rounded = Math.round(clamp01(value) * 10000) / 10000;
  if (Number.isInteger(rounded)) {
    return `${rounded}`;
  }
  return `${rounded}`.replace(/(\.\d*?[1-9])0+$/u, '$1').replace(/\.0$/u, '');
}

function parsePolygonValue(value) {
  const raw = String(value || '').trim();
  if (!raw) {
    return { points: [], isMultiRegion: false };
  }

  const regions = raw.split(';').map((item) => item.trim()).filter(Boolean);
  const first = regions[0] || '';
  const tokens = first.split(',').map((item) => item.trim()).filter(Boolean);
  if (tokens.length < 6 || tokens.length % 2 !== 0) {
    return { points: [], isMultiRegion: regions.length > 1 };
  }

  const points = [];
  for (let index = 0; index < tokens.length; index += 2) {
    const x = Number(tokens[index]);
    const y = Number(tokens[index + 1]);
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      return { points: [], isMultiRegion: regions.length > 1 };
    }
    points.push({ x: clamp01(x), y: clamp01(y) });
  }
  return { points, isMultiRegion: regions.length > 1 };
}

function pointsToPolygonValue(points) {
  if (!Array.isArray(points) || points.length < 3) {
    return '';
  }
  return points.flatMap((point) => [formatCoordinate(point.x), formatCoordinate(point.y)]).join(',');
}

function rectToPoints(start, end) {
  const left = Math.min(start.x, end.x);
  const right = Math.max(start.x, end.x);
  const top = Math.min(start.y, end.y);
  const bottom = Math.max(start.y, end.y);
  if (Math.abs(right - left) < 0.001 || Math.abs(bottom - top) < 0.001) {
    return [];
  }
  return [
    { x: left, y: top },
    { x: right, y: top },
    { x: right, y: bottom },
    { x: left, y: bottom },
  ];
}

function pointsToSvgPoints(points) {
  return (Array.isArray(points) ? points : [])
    .map((point) => `${point.x * 100} ${point.y * 100}`)
    .join(' ');
}

function resolveNormalizedPoint(event, node) {
  const rect = node?.getBoundingClientRect?.();
  if (!rect || !rect.width || !rect.height) {
    return null;
  }
  return {
    x: clamp01((event.clientX - rect.left) / rect.width),
    y: clamp01((event.clientY - rect.top) / rect.height),
  };
}

function replacePoint(points, index, nextPoint) {
  return (Array.isArray(points) ? points : []).map((point, currentIndex) => (
    currentIndex === index ? nextPoint : point
  ));
}

export default function RecognitionRegionEditor({
  value = '',
  onChange = () => {},
  previewImageUrl = '',
  previewLoading = false,
  previewError = '',
  onRefreshPreview = null,
  streamLabel = '',
  disabled = false,
}) {
  const { token } = theme.useToken();
  const stageRef = useRef(null);
  const [mode, setMode] = useState('rect');
  const [rectDraft, setRectDraft] = useState(null);
  const parsedValue = useMemo(() => parsePolygonValue(value), [value]);
  const [polygonDraft, setPolygonDraft] = useState(parsedValue.points);
  const [dragState, setDragState] = useState(null);
  const polygonDraftRef = useRef(polygonDraft);

  useEffect(() => {
    setPolygonDraft(parsedValue.points);
  }, [parsedValue.points]);

  useEffect(() => {
    polygonDraftRef.current = polygonDraft;
  }, [polygonDraft]);

  const activePoints = useMemo(() => {
    if (mode === 'polygon' && polygonDraft.length > 0) {
      return polygonDraft;
    }
    if (mode === 'rect' && rectDraft?.start && rectDraft?.end) {
      return rectToPoints(rectDraft.start, rectDraft.end);
    }
    return parsedValue.points;
  }, [mode, polygonDraft, rectDraft, parsedValue.points]);

  const handleSetMode = (nextMode) => {
    setMode(nextMode);
    setRectDraft(null);
    setDragState(null);
    if (nextMode === 'polygon') {
      setPolygonDraft(parsedValue.points);
    }
  };

  const handleRectMouseDown = (event) => {
    if (disabled || mode !== 'rect') return;
    const point = resolveNormalizedPoint(event, stageRef.current);
    if (!point) return;
    setRectDraft({ start: point, end: point });
  };

  const handleRectMouseMove = (event) => {
    if (disabled || mode !== 'rect' || !rectDraft?.start) return;
    const point = resolveNormalizedPoint(event, stageRef.current);
    if (!point) return;
    setRectDraft((prev) => (prev?.start ? { ...prev, end: point } : prev));
  };

  const finishRectangle = (event) => {
    if (disabled || mode !== 'rect' || !rectDraft?.start) return;
    const fallbackEnd = rectDraft.end || rectDraft.start;
    const point = resolveNormalizedPoint(event, stageRef.current) || fallbackEnd;
    const points = rectToPoints(rectDraft.start, point);
    setRectDraft(null);
    if (points.length >= 3) {
      onChange(pointsToPolygonValue(points));
    }
  };

  const handlePolygonClick = (event) => {
    if (disabled || mode !== 'polygon' || dragState) return;
    const point = resolveNormalizedPoint(event, stageRef.current);
    if (!point) return;
    setPolygonDraft((prev) => [...prev, point]);
  };

  const handlePointMouseDown = (index, event) => {
    if (disabled) return;
    event.preventDefault();
    event.stopPropagation();
    const point = resolveNormalizedPoint(event, stageRef.current);
    if (!point) return;

    if (mode === 'polygon') {
      const basePoints = polygonDraftRef.current.length > 0 ? polygonDraftRef.current : parsedValue.points;
      if (!basePoints[index]) return;
      setPolygonDraft(basePoints);
      setDragState({ kind: 'polygon', index });
      return;
    }

    if (mode === 'rect' && activePoints.length === 4) {
      const oppositePoint = activePoints[RECT_OPPOSITE_INDEX[index]];
      if (!oppositePoint) return;
      setRectDraft({ start: oppositePoint, end: point });
      setDragState({ kind: 'rect', oppositePoint });
    }
  };

  useEffect(() => {
    if (!dragState) return undefined;

    const handleMouseMove = (event) => {
      const point = resolveNormalizedPoint(event, stageRef.current);
      if (!point) return;
      if (dragState.kind === 'polygon') {
        setPolygonDraft((prev) => {
          const basePoints = prev.length > 0 ? prev : parsedValue.points;
          return replacePoint(basePoints, dragState.index, point);
        });
        return;
      }
      if (dragState.kind === 'rect') {
        setRectDraft({ start: dragState.oppositePoint, end: point });
      }
    };

    const handleMouseUp = (event) => {
      const point = resolveNormalizedPoint(event, stageRef.current);
      if (!point) {
        setDragState(null);
        if (dragState.kind === 'rect') {
          setRectDraft(null);
        }
        return;
      }

      if (dragState.kind === 'polygon') {
        const basePoints = polygonDraftRef.current.length > 0 ? polygonDraftRef.current : parsedValue.points;
        const nextPoints = replacePoint(basePoints, dragState.index, point);
        setPolygonDraft(nextPoints);
        onChange(pointsToPolygonValue(nextPoints));
      }

      if (dragState.kind === 'rect') {
        const nextPoints = rectToPoints(dragState.oppositePoint, point);
        setRectDraft(null);
        if (nextPoints.length >= 3) {
          onChange(pointsToPolygonValue(nextPoints));
        }
      }

      setDragState(null);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [dragState, onChange, parsedValue.points]);

  const handleUndoPoint = () => {
    setPolygonDraft((prev) => prev.slice(0, -1));
  };

  const handleClosePolygon = () => {
    if (polygonDraft.length < 3) return;
    onChange(pointsToPolygonValue(polygonDraft));
  };

  const handleClear = () => {
    setRectDraft(null);
    setPolygonDraft([]);
    onChange('');
  };

  const handleFullFrame = () => {
    setRectDraft(null);
    setPolygonDraft(parsePolygonValue(FULL_FRAME_REGION).points);
    onChange(FULL_FRAME_REGION);
  };

  return (
    <div
      style={{
        display: 'grid',
        gap: 12,
        padding: 12,
        border: `1px solid ${token.colorBorderSecondary}`,
        borderRadius: 6,
        background: token.colorBgContainer,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 2 }}>识别区域</div>
          <Text type="secondary" style={{ fontSize: 12 }}>
            直接在画面上框选或点选，不需要手填坐标
          </Text>
        </div>
        <Segmented
          value={mode}
          onChange={handleSetMode}
          disabled={disabled}
          options={[
            { label: '矩形框选', value: 'rect' },
            { label: '多边形点选', value: 'polygon' },
          ]}
        />
      </div>

      {parsedValue.isMultiRegion ? (
        <Alert
          type="warning"
          showIcon
          message="当前坐标包含多区域。画布编辑会按单区域保存。"
        />
      ) : null}

      <div
        ref={stageRef}
        aria-label="布控区域画布"
        onMouseDown={handleRectMouseDown}
        onMouseMove={handleRectMouseMove}
        onMouseUp={finishRectangle}
        onMouseLeave={finishRectangle}
        onClick={handlePolygonClick}
        style={{
          position: 'relative',
          width: '100%',
          aspectRatio: STAGE_ASPECT_RATIO,
          borderRadius: 6,
          overflow: 'hidden',
          border: `1px solid ${token.colorBorder}`,
          background: '#020617',
          cursor: disabled ? 'not-allowed' : mode === 'rect' ? 'crosshair' : 'copy',
          userSelect: 'none',
        }}
      >
        {previewImageUrl ? (
          <img
            alt="布控区域当前帧"
            src={previewImageUrl}
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }}
          />
        ) : (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'rgba(255,255,255,0.65)',
              fontSize: 13,
              letterSpacing: 0,
              textAlign: 'center',
              padding: '0 24px',
            }}
          >
            {previewLoading
              ? '正在抓取当前帧...'
              : previewError
                ? previewError
                : (streamLabel ? `预览流：${streamLabel}` : '选择视频流后即可在这里划定区域')}
          </div>
        )}

        <svg
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
        >
          {activePoints.length >= 2 ? (
            mode === 'polygon' && polygonDraft.length > 0 && polygonDraft.length < 3 ? (
              <polyline
                points={pointsToSvgPoints(activePoints)}
                fill="rgba(59,130,246,0.18)"
                stroke="#60a5fa"
                strokeWidth="0.7"
              />
            ) : (
              <polygon
                points={pointsToSvgPoints(activePoints)}
                fill="rgba(59,130,246,0.20)"
                stroke="#60a5fa"
                strokeWidth="0.7"
              />
            )
          ) : null}
          {activePoints.map((point, index) => (
            <circle
              key={`${point.x}-${point.y}-${index}`}
              data-testid={`roi-handle-${index}`}
              cx={point.x * 100}
              cy={point.y * 100}
              r="1.1"
              fill="#f8fafc"
              stroke="#2563eb"
              strokeWidth="0.4"
              style={{ cursor: disabled ? 'not-allowed' : 'grab' }}
              onMouseDown={(event) => handlePointMouseDown(index, event)}
              onClick={(event) => event.stopPropagation()}
            />
          ))}
        </svg>
      </div>

      <Space wrap>
        <Button onClick={onRefreshPreview} disabled={disabled || !streamLabel || !onRefreshPreview} loading={previewLoading}>
          刷新当前帧
        </Button>
        <Button onClick={handleFullFrame} disabled={disabled}>
          全屏区域
        </Button>
        <Button onClick={handleClear} disabled={disabled}>
          清空区域
        </Button>
        {mode === 'polygon' ? (
          <>
            <Button onClick={handleUndoPoint} disabled={disabled || polygonDraft.length === 0}>
              撤销一点
            </Button>
            <Button type="primary" onClick={handleClosePolygon} disabled={disabled || polygonDraft.length < 3}>
              闭合区域
            </Button>
          </>
        ) : null}
      </Space>

      <div style={{ display: 'grid', gap: 4 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          当前区域坐标（自动生成）
        </Text>
        <div
          style={{
            minHeight: 44,
            padding: '10px 12px',
            borderRadius: 6,
            background: token.colorFillAlter,
            border: `1px solid ${token.colorBorderSecondary}`,
            fontSize: 12,
            lineHeight: 1.5,
            wordBreak: 'break-all',
          }}
        >
          {String(value || '').trim() || '未设置'}
        </div>
      </div>

      {previewError ? (
        <Alert
          type="warning"
          showIcon
          message={previewError}
        />
      ) : null}
    </div>
  );
}

RecognitionRegionEditor.propTypes = {
  value: PropTypes.string,
  onChange: PropTypes.func,
  previewImageUrl: PropTypes.string,
  previewLoading: PropTypes.bool,
  previewError: PropTypes.string,
  onRefreshPreview: PropTypes.func,
  streamLabel: PropTypes.string,
  disabled: PropTypes.bool,
};
