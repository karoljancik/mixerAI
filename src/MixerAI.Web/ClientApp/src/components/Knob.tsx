
import React, { useRef, useState, useEffect } from 'react';

type KnobProps = {
  value: number;
  min: number;
  max: number;
  centerValue?: number;
  label: string;
  onChange: (val: number) => void;
};

export function Knob({ value, min, max, centerValue, label, onChange }: KnobProps) {
  const [isDragging, setIsDragging] = useState(false);
  const startY = useRef(0);
  const startPct = useRef(0);

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

  // Constrain to physical arc
  const rotation = -150 + (pct * 300);

  const handlePointerDown = (e: React.PointerEvent) => {
    e.preventDefault();
    setIsDragging(true);
    startY.current = e.clientY;
    startPct.current = pct;
  };

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY < 0 ? 1 : -1;
    let newPct = pct + (delta * 0.05); // 5% physical turn per tick
    if (newPct > 1) newPct = 1;
    if (newPct < 0) newPct = 0;
    applyPct(newPct);
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
      onChange(newVal);
  };

  useEffect(() => {
    if (!isDragging) return;

    const handlePointerMove = (e: PointerEvent) => {
      const deltaY = startY.current - e.clientY;
      // 1 pixel = 1% drag roughly
      let newPct = startPct.current + (deltaY * 0.008);
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
      <div 
        className="eq-knob" 
        onPointerDown={handlePointerDown} 
        onWheel={handleWheel}
        style={{ transform: `rotate(${rotation}deg)` }}
      >
        <div className="eq-knob-indicator"></div>
      </div>
      <span className="eq-label">{label}</span>
    </div>
  );
}
