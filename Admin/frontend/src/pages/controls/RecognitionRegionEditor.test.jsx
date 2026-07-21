import React, { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { ConfigProvider } from 'antd';
import RecognitionRegionEditor from './RecognitionRegionEditor';

function Harness({ initialValue = '' }) {
  const [value, setValue] = useState(initialValue);
  return (
    <ConfigProvider>
      <RecognitionRegionEditor value={value} onChange={setValue} />
      <output data-testid="polygon-value">{value}</output>
    </ConfigProvider>
  );
}

function setCanvasRect(node, { left = 0, top = 0, width = 200, height = 100 } = {}) {
  Object.defineProperty(node, 'getBoundingClientRect', {
    configurable: true,
    value: () => ({
      left,
      top,
      width,
      height,
      right: left + width,
      bottom: top + height,
      x: left,
      y: top,
      toJSON: () => ({}),
    }),
  });
}

describe('RecognitionRegionEditor', () => {
  it('draws rectangle selections into normalized polygon coordinates', () => {
    render(<Harness />);

    const canvas = screen.getByLabelText('布控区域画布');
    setCanvasRect(canvas);

    fireEvent.mouseDown(canvas, { clientX: 20, clientY: 10 });
    fireEvent.mouseMove(canvas, { clientX: 180, clientY: 80 });
    fireEvent.mouseUp(canvas, { clientX: 180, clientY: 80 });

    expect(screen.getByTestId('polygon-value')).toHaveTextContent('0.1,0.1,0.9,0.1,0.9,0.8,0.1,0.8');
  });

  it('supports polygon point selection and closing the region', () => {
    render(<Harness />);

    fireEvent.click(screen.getByRole('radio', { name: '多边形点选' }));

    const canvas = screen.getByLabelText('布控区域画布');
    setCanvasRect(canvas);

    fireEvent.click(canvas, { clientX: 20, clientY: 20 });
    fireEvent.click(canvas, { clientX: 160, clientY: 20 });
    fireEvent.click(canvas, { clientX: 140, clientY: 80 });
    fireEvent.click(screen.getByRole('button', { name: '闭合区域' }));

    expect(screen.getByTestId('polygon-value')).toHaveTextContent('0.1,0.2,0.8,0.2,0.7,0.8');
  });

  it('can reset the region to full frame with one action', () => {
    render(<Harness initialValue="0.1,0.1,0.9,0.1,0.9,0.9,0.1,0.9" />);

    fireEvent.click(screen.getByRole('button', { name: '全屏区域' }));

    expect(screen.getByTestId('polygon-value')).toHaveTextContent('0,0,1,0,1,1,0,1');
  });

  it('drags an existing polygon control point to a new position', () => {
    render(<Harness initialValue="0.1,0.1,0.9,0.1,0.9,0.8,0.1,0.8" />);

    fireEvent.click(screen.getByRole('radio', { name: '多边形点选' }));

    const canvas = screen.getByLabelText('布控区域画布');
    setCanvasRect(canvas);
    const [firstHandle] = canvas.querySelectorAll('circle');

    fireEvent.mouseDown(firstHandle, { clientX: 20, clientY: 10 });
    fireEvent.mouseMove(document, { clientX: 40, clientY: 30 });
    fireEvent.mouseUp(document, { clientX: 40, clientY: 30 });

    expect(screen.getByTestId('polygon-value')).toHaveTextContent('0.2,0.3,0.9,0.1,0.9,0.8,0.1,0.8');
  });

  it('drags an existing rectangle corner while keeping the opposite corner fixed', () => {
    render(<Harness initialValue="0.1,0.1,0.9,0.1,0.9,0.8,0.1,0.8" />);

    const canvas = screen.getByLabelText('布控区域画布');
    setCanvasRect(canvas);
    const [firstHandle] = canvas.querySelectorAll('circle');

    fireEvent.mouseDown(firstHandle, { clientX: 20, clientY: 10 });
    fireEvent.mouseMove(document, { clientX: 40, clientY: 30 });
    fireEvent.mouseUp(document, { clientX: 40, clientY: 30 });

    expect(screen.getByTestId('polygon-value')).toHaveTextContent('0.2,0.3,0.9,0.3,0.9,0.8,0.2,0.8');
  });

  it('shows the snapshot error in the preview canvas', () => {
    render(
      <ConfigProvider>
        <RecognitionRegionEditor
          streamLabel="live / simcam02"
          previewError="截图失败：拉流地址不可访问"
        />
      </ConfigProvider>,
    );

    expect(screen.getByLabelText('布控区域画布')).toHaveTextContent('截图失败：拉流地址不可访问');
  });
});
