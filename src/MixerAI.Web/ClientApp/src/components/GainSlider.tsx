import React, { useEffect, useRef } from "react";
import "./GainSlider.css";

type GainSliderProps = {
  value: number;
  min: number;
  max: number;
  label: string;
  onChange: (val: number) => void;
};

export const GainSlider = React.memo(({ value, min, max, label, onChange }: GainSliderProps) => {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const valueRef = useRef(value);
  valueRef.current = value;

  useEffect(() => {
    const input = inputRef.current;
    if (!input) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY < 0 ? 0.12 : -0.12; // Faster wheel scrolling
      const nextValue = Math.min(max, Math.max(min, valueRef.current + delta));
      onChange(Number(nextValue.toFixed(2)));
    };

    input.addEventListener('wheel', handleWheel, { passive: false });
    return () => input.removeEventListener('wheel', handleWheel);
  }, [min, max]); // onChange is normally stable from App or memoized

  return (
    <label className="gain-slider">
      <span className="gain-slider-label">{label}</span>
      <input
        ref={inputRef}
        className="gain-slider-input"
        type="range"
        min={min}
        max={max}
        step="0.01"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
});
