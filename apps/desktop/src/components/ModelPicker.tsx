import type { ModelInfo } from "../types";

interface Props {
  models: ModelInfo[];
  value: string | null;
  onChange: (modelId: string) => void;
  disabled?: boolean;
}

export default function ModelPicker({ models, value, onChange, disabled }: Props) {
  const known = models.some((m) => m.model_id === value);
  return (
    <select className="model-picker" value={value ?? ""} onChange={(e) => onChange(e.target.value)} disabled={disabled || models.length === 0} aria-label="Model">
      {!known && <option value="">{value ? `${value} (yüklü değil)` : "Model seçin"}</option>}
      {models.map((m) => (
        <option key={`${m.provider_id}/${m.model_id}`} value={m.model_id}>
          {m.model_id} {m.parameter_size ? `· ${m.parameter_size}` : ""} · {m.location === "local" ? "yerel" : "uzak"}
        </option>
      ))}
    </select>
  );
}
