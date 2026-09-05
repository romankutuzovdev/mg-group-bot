import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "./api";

type FxRateContextValue = {
  fxRate: number | null;
  fxSource: string | null;
  loading: boolean;
  setFxRate: (value: number) => Promise<void>;
  reload: () => Promise<void>;
};

const FxRateContext = createContext<FxRateContextValue | null>(null);

export function FxRateProvider({ children }: { children: ReactNode }) {
  const [fxRate, setFxRateState] = useState<number | null>(null);
  const [fxSource, setFxSource] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    const state = await api.state();
    setFxRateState(state.fx_rate ?? null);
    setFxSource(state.fx_source ?? null);
    setLoading(false);
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const setFxRate = useCallback(async (value: number) => {
    const data = await api.setFxRate(value);
    setFxRateState(data.fx_rate);
    setFxSource(data.fx_source ?? "manual");
  }, []);

  return (
    <FxRateContext.Provider value={{ fxRate, fxSource, loading, setFxRate, reload }}>
      {children}
    </FxRateContext.Provider>
  );
}

export function useFxRate() {
  const ctx = useContext(FxRateContext);
  if (!ctx) {
    throw new Error("useFxRate must be used inside FxRateProvider");
  }
  return ctx;
}
