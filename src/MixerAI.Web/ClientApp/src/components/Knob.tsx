
import React, { useRef, useState, useEffect } from 'react';

type KnobProps = {
  value: number;
  min: number;
  max: number;
  centerValue?: number;
  label: string;
  onChange: (val: number) => void;
};

export const Knob = React.memo(({ value, min, max, centerValue, label, onChange }: KnobProps) => {
  const [isDragging, setIsDragging] = useState(false);
  const startY = useRef(0);
  const startPct = useRef(0);
  const lastEmittedValue = useRef(value);

  const center = centerValue !== undefined ? centerValue : (max + min) / 2;

  // Convert current value to a 0.0 - 1.0 physical rotation percentage
  let pct = 0;
  if (value < center) {
    const range = center - min;
    pct = range === 0 ? 0 : ((value - min) / range) * 0.5;
  } else {
    const range = max - center;
    pct = range === 0 ? 0.5 : 0.5 + ((value - center) / range) * 0.5;
  }

  // Constrain to physical arc for CSS rotation
  const rotation = -150 + (pct * 300);

  // SVG parameters for the ring arc
  const size = 38;
  const stroke = 3;
  const radius = (size - stroke) / 2;
  const circumference = radius * 2 * Math.PI;
  const arcLength = 300; // Degrees
  const rotationOffset = 90 + (360 - arcLength) / 2; // Point to start of arc

  const handlePointerDown = (e: React.PointerEvent) => {
    e.preventDefault();
    setIsDragging(true);
    startY.current = e.clientY;
    startPct.current = pct;
  };

  const applyPct = (newPct: number) => {
    let newVal = 0;
    if (newPct < 0.5) {
      const ratio = newPct / 0.5;
      newVal = min + ratio * (center - min);
    } else {
      const ratio = (newPct - 0.5) / 0.5;
      newVal = center + ratio * (max - center);
    }

    if (Math.abs(newVal - lastEmittedValue.current) > 0.01) {
      lastEmittedValue.current = newVal;
      onChange(newVal);
    }
  };

  const knobRef = useRef<HTMLDivElement | null>(null);
  const pctRef = useRef(pct);
  pctRef.current = pct;

  useEffect(() => {
    const knob = knobRef.current;
    if (!knob) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY < 0 ? 1 : -1;
      let newPct = pctRef.current + (delta * 0.05); // Much faster wheel (was 0.015)
      if (newPct > 1) newPct = 1;
      if (newPct < 0) newPct = 0;
      applyPct(newPct);
    };

    knob.addEventListener('wheel', handleWheel, { passive: false });
    return () => knob.removeEventListener('wheel', handleWheel);
  }, []); // Only once

  useEffect(() => {
    if (!isDragging) return;

    const handlePointerMove = (e: PointerEvent) => {
      const deltaY = startY.current - e.clientY;
      let newPct = startPct.current + (deltaY * 0.02); // Fast drag (was 2.0 which was too much)
      if (newPct > 1) newPct = 1;
      if (newPct < 0) newPct = 0;
      applyPct(newPct);
    };

    const handlePointerUp = () => {
      setIsDragging(false);
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);

    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
    };
  }, [isDragging, max, min, center, onChange]);

  return (
    <div className="eq-knob-container">
      <div className="eq-knob-visual-wrapper">
        <svg className="eq-knob-ring" width={size} height={size}>
          <circle
            className="eq-knob-ring-bg"
            stroke="rgba(255,255,255,0.05)"
            strokeWidth={stroke}
            fill="transparent"
            r={radius}
            cx={size / 2}
            cy={size / 2}
            style={{
              strokeDasharray: `${circumference} ${circumference}`,
              strokeDashoffset: circumference - (arcLength / 360) * circumference,
              transform: `rotate(${rotationOffset}deg)`,
              transformOrigin: '50% 50%'
            }}
          />
          <circle
            className="eq-knob-ring-progress"
            stroke="var(--accent)"
            strokeWidth={stroke}
            strokeLinecap="round"
            fill="transparent"
            r={radius}
            cx={size / 2}
            cy={size / 2}
            style={{
              strokeDasharray: `${circumference} ${circumference}`,
              strokeDashoffset: circumference - (pct * (arcLength / 360)) * circumference,
              transform: `rotate(${rotationOffset}deg)`,
              transformOrigin: '50% 50%',
              filter: 'drop-shadow(0 0 2px var(--accent))'
            }}
          />
        </svg>
        <div
          ref={knobRef}
          className="eq-knob"
          onPointerDown={handlePointerDown}
          style={{ transform: `rotate(${rotation}deg)` }}
        >
          <div className="eq-knob-indicator"></div>
        </div>
      </div>
      <span className="eq-label">{label}</span>
    </div>
  );
});
