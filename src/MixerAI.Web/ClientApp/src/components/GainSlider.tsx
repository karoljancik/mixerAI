import "./GainSlider.css";

type GainSliderProps = {
  value: number;
  min: number;
  max: number;
  label: string;
  onChange: (val: number) => void;
};

export function GainSlider({ value, min, max, label, onChange }: GainSliderProps) {
  const handleWheel = (e: React.WheelEvent<HTMLInputElement>) => {
    e.preventDefault();

    const delta = e.deltaY < 0 ? 0.1 : -0.1;
    const nextValue = Math.min(max, Math.max(min, value + delta));
    onChange(Number(nextValue.toFixed(2)));
  };

  return (
    <label className="gain-slider">
      <span className="gain-slider-label">{label}</span>
      <input
        className="gain-slider-input"
        type="range"
        min={min}
        max={max}
        step="0.01"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        onWheel={handleWheel}
      />
    </label>
  );
}
