import { FormEvent, useEffect, useState } from "react";
import { useFxRate } from "./FxRateContext";

export default function FxRateControl({ onSaved }: { onSaved?: () => void }) {
  const { fxRate, fxSource, loading, setFxRate } = useFxRate();
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (fxRate != null) {
      setDraft(String(fxRate));
    }
  }, [fxRate]);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const value = Number(draft.replace(",", "."));
    if (!value || value <= 0) {
      setError("Введите курс больше 0");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await setFxRate(value);
      onSaved?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить курс");
    } finally {
      setSaving(false);
    }
  };

  const sourceLabel =
    fxSource === "manual" ? "ручной" : fxSource === "auto" ? "авто" : fxSource === "default" ? "по умолчанию" : "";

  return (
    <form className="fx-control" onSubmit={(event) => void onSubmit(event)}>
      <label className="fx-label" htmlFor="fx-rate-input">
        Курс GBP→USD
        {sourceLabel ? <span className="fx-badge">{sourceLabel}</span> : null}
      </label>
      <div className="fx-row">
        <input
          id="fx-rate-input"
          className="field fx-input"
          type="number"
          min="0"
          step="0.0001"
          placeholder="1.27"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={loading || saving}
        />
        <button className="btn ghost small" type="submit" disabled={loading || saving}>
          {saving ? "…" : "OK"}
        </button>
      </div>
      {error ? <div className="error fx-error">{error}</div> : null}
    </form>
  );
}
