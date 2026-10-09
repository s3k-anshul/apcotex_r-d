import React, { createContext, useContext, useState, useEffect, useRef } from 'react';
import * as api from '../services/researchApi';
import { isRecipeDemoMode } from '../config/recipeDemoMode';
import {
  getDemoCycle,
  getDemoRevisedRecipes,
} from '../services/recipeDemoService';

export interface Step1Inputs {
  targetProduct: string;
  processType: 'Batch' | 'Continuous' | 'No Preference';
  temperatureMin: string;
  temperatureMax: string;
  temperatureUnit: string;
  desired: Record<string, { min: string; max: string; target?: string }>;
  competitors: { id: string; name: string }[];
  competitorValues: Record<string, Record<string, string>>;
}

export interface GenerationSnapshot {
  targetProduct: string;
  reportId: string | null;
  processType: string;
  temperatureMin: string;
  temperatureMax: string;
  desiredJson: string;
  competitorValuesJson: string;
}

export interface GenerationState {
  hasGeneratedRecipes: boolean;
  generationContextSnapshot: GenerationSnapshot | null;
  inputsChangedSinceGeneration: boolean;
}

interface RecipeContextType {
  cycleId: string | null;
  cycle: any | null;
  candidates: any[];
  selectedCandidate: any | null;
  trial: any | null;
  optimizedCandidates: any[];
  selectedOptimized: any | null;
  
  loading: boolean;
  generating: boolean;
  optimizing: boolean;
  error: string | null;
  demoMode: boolean;

  // Explicit Generation & Navigation State
  generationState: GenerationState;
  step1Inputs: Step1Inputs;
  setStep1Inputs: (updates: Partial<Step1Inputs>) => void;
  setGenerationSnapshot: (snapshot: GenerationSnapshot) => void;
  markInputsChanged: () => void;
  resetGenerationSession: () => void;
  updateCandidateLocally: (candidateId: string, updatedRecipeData: any, name?: string) => void;

  setCycleId: (id: string | null) => void;
  clearError: () => void;
  loadDemoSession: (compoundName?: string) => void;
  loadCycle: (id: string) => Promise<void>;
  createCycle: (payload: any) => Promise<string>;
  updateCycle: (payload: any) => Promise<void>;
  generateRecipes: (targetCycleId?: string) => Promise<void>;
  selectCandidate: (candidateId: string) => Promise<void>;
  createTrial: (payload: any) => Promise<any>;
  updateTrial: (payload: any) => Promise<void>;
  generateOptimization: () => Promise<void>;
  selectOptimized: (optimizedId: string) => Promise<void>;
  loadTrial: (trialId: string) => Promise<any>;
  resetContext: () => void;
  saveSavedRecipe: (payload: any) => Promise<any>;
  updateCandidateRecipeData: (
    candidateId: string,
    payload: { recipe_data: any; name?: string }
  ) => Promise<any>;
  updateOptimizedCandidateData: (
    candidateId: string,
    payload: { recipe_data: any; name?: string }
  ) => Promise<any>;
}

const RecipeContext = createContext<RecipeContextType | undefined>(undefined);

export function RecipeProvider({ children }: { children: React.ReactNode }) {
  const [cycleId, setCycleIdState] = useState<string | null>(() => {
    const stored = localStorage.getItem('activeRecipeCycleId');
    if (stored && stored.includes('demo')) {
      localStorage.removeItem('activeRecipeCycleId');
      return null;
    }
    return stored;
  });
  const cycleIdRef = useRef<string | null>(cycleId);
  const [cycle, setCycle] = useState<any | null>(null);
  const [candidates, setCandidates] = useState<any[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState<any | null>(null);
  const [trial, setTrial] = useState<any | null>(null);
  const trialRef = useRef<any | null>(null);
  const [optimizedCandidates, setOptimizedCandidates] = useState<any[]>([]);
  const [selectedOptimized, setSelectedOptimized] = useState<any | null>(null);

  // Step 1 persistent inputs in memory across Step 1 <-> Step 2 navigation
  const [step1Inputs, setStep1InputsState] = useState<Step1Inputs>({
    targetProduct: '',
    processType: 'No Preference',
    temperatureMin: '',
    temperatureMax: '',
    temperatureUnit: '°C',
    desired: {},
    competitors: [{ id: 'c1', name: '' }],
    competitorValues: {},
  });

  // Explicit Generation State
  const [generationState, setGenerationState] = useState<GenerationState>({
    hasGeneratedRecipes: false,
    generationContextSnapshot: null,
    inputsChangedSinceGeneration: false,
  });

  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [optimizing, setOptimizing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setStep1Inputs = (updates: Partial<Step1Inputs>) => {
    setStep1InputsState((prev) => {
      const next = { ...prev, ...updates };
      // Check if next inputs differ from generationContextSnapshot
      if (generationState.generationContextSnapshot) {
        const snap = generationState.generationContextSnapshot;
        const isChanged =
          snap.targetProduct !== next.targetProduct.trim() ||
          snap.processType !== next.processType ||
          snap.temperatureMin !== next.temperatureMin ||
          snap.temperatureMax !== next.temperatureMax ||
          snap.desiredJson !== JSON.stringify(next.desired) ||
          snap.competitorValuesJson !== JSON.stringify(next.competitorValues);
        if (isChanged !== generationState.inputsChangedSinceGeneration) {
          setGenerationState((g) => ({ ...g, inputsChangedSinceGeneration: isChanged }));
        }
      }
      return next;
    });
  };

  const setGenerationSnapshot = (snapshot: GenerationSnapshot) => {
    setGenerationState({
      hasGeneratedRecipes: true,
      generationContextSnapshot: snapshot,
      inputsChangedSinceGeneration: false,
    });
  };

  const markInputsChanged = () => {
    setGenerationState((g) => ({
      ...g,
      inputsChangedSinceGeneration: true,
    }));
  };

  const resetGenerationSession = () => {
    resetContext();
    setGenerationState({
      hasGeneratedRecipes: false,
      generationContextSnapshot: null,
      inputsChangedSinceGeneration: false,
    });
    setStep1InputsState({
      targetProduct: '',
      processType: 'No Preference',
      temperatureMin: '',
      temperatureMax: '',
      temperatureUnit: '°C',
      desired: {},
      competitors: [{ id: 'c1', name: '' }],
      competitorValues: {},
    });
  };

  const updateCandidateLocally = (candidateId: string, updatedRecipeData: any, name?: string) => {
    setCandidates((prev) =>
      prev.map((c) =>
        c.id === candidateId
          ? {
              ...c,
              recipe_data: updatedRecipeData,
              ...(name ? { name } : {}),
            }
          : c
      )
    );
    if (selectedCandidate?.id === candidateId) {
      setSelectedCandidate((prev: any) =>
        prev
          ? {
              ...prev,
              recipe_data: updatedRecipeData,
              ...(name ? { name } : {}),
            }
          : null
      );
    }
  };

  const setCycleId = (id: string | null) => {
    cycleIdRef.current = id;
    setCycleIdState(id);
    if (id && !id.includes('demo')) {
      localStorage.setItem('activeRecipeCycleId', id);
    } else {
      localStorage.removeItem('activeRecipeCycleId');
    }
  };

  const resetContext = () => {
    cycleIdRef.current = null;
    setCycleIdState(null);
    setCycle(null);
    setCandidates([]);
    setSelectedCandidate(null);
    trialRef.current = null;
    setTrial(null);
    setOptimizedCandidates([]);
    setSelectedOptimized(null);
    setError(null);
    setGenerationState({
      hasGeneratedRecipes: false,
      generationContextSnapshot: null,
      inputsChangedSinceGeneration: false,
    });
    localStorage.removeItem('activeRecipeCycleId');
  };

  const clearError = () => setError(null);

  /** Dedicated development fixture path — only invoked by explicit manual test action. */
  const loadDemoSession = (compoundName = "Demo NBR") => {
    const demo = getDemoCycle(compoundName);
    setError(null);
    setCycle(demo);
    setCycleId(demo.id);
    setCandidates(demo.candidates);
    setSelectedCandidate(null);
    setTrial(null);
    setOptimizedCandidates([]);
    setSelectedOptimized(null);
    if (import.meta.env.DEV) {
      console.info(
        "[RECIPE DEMO] loadDemoSession",
        "candidates=",
        demo.candidates?.length ?? 0
      );
    }
  };

  const loadCycle = async (id: string) => {
    if (id?.includes("demo")) {
      resetContext();
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await api.getRecipeCycle(id);
      setCycle(data);
      
      const cands = data.candidates || [];
      setCandidates(cands);
      
      const selected = cands.find((c: any) => c.is_selected);
      setSelectedCandidate(selected || null);

      const trials = data.trials || [];
      if (trials.length > 0) {
        const activeTrial = trials[0];
        setTrial(activeTrial);
        const opts = activeTrial.optimized_candidates || [];
        setOptimizedCandidates(opts);
        const selOpt = opts.find((o: any) => o.is_selected);
        setSelectedOptimized(selOpt || null);
      } else {
        setTrial(null);
        setOptimizedCandidates([]);
        setSelectedOptimized(null);
      }
      
      // Rehydrate step1Inputs from cycle data so navigating back to Step 1 or refreshing never loses target properties
      const loadedDesired: Record<string, { min: string; max: string; target?: string }> = {};
      if (Array.isArray(data.target_properties)) {
        data.target_properties.forEach((tp: any) => {
          const feat = tp.feature || tp.property || tp.name || tp.id;
          if (feat) {
            loadedDesired[feat] = {
              min: tp.min !== undefined && tp.min !== null ? String(tp.min) : (tp.min_value !== undefined && tp.min_value !== null ? String(tp.min_value) : ''),
              max: tp.max !== undefined && tp.max !== null ? String(tp.max) : (tp.max_value !== undefined && tp.max_value !== null ? String(tp.max_value) : ''),
              target: tp.target !== undefined && tp.target !== null ? String(tp.target) : (tp.target_value !== undefined && tp.target_value !== null ? String(tp.target_value) : ''),
            };
          }
        });
      }

      // Rehydrate process_type and temperature_range if present
      let loadedProcessType: 'Batch' | 'Continuous' | 'No Preference' = 'No Preference';
      if (data.process_type) {
        const ptLow = String(data.process_type).toLowerCase();
        if (ptLow === 'batch') loadedProcessType = 'Batch';
        else if (ptLow === 'continuous') loadedProcessType = 'Continuous';
      }
      let loadedTempMin = '';
      let loadedTempMax = '';
      let loadedTempUnit = '°C';
      if (data.temperature_range) {
        if (typeof data.temperature_range === 'object') {
          loadedTempMin = data.temperature_range.min !== undefined && data.temperature_range.min !== null ? String(data.temperature_range.min) : '';
          loadedTempMax = data.temperature_range.max !== undefined && data.temperature_range.max !== null ? String(data.temperature_range.max) : '';
          loadedTempUnit = data.temperature_range.unit || '°C';
        } else if (typeof data.temperature_range === 'string') {
          const m = data.temperature_range.match(/(-?\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(-?\d+(?:\.\d+)?)/);
          if (m) {
            loadedTempMin = m[1];
            loadedTempMax = m[2];
          }
        }
      }

      // Rehydrate competitors and competitorValues if available
      let loadedCompetitors: Array<{ id: string; name: string }> = [{ id: 'c1', name: '' }];
      const loadedCompValues: Record<string, Record<string, string>> = {};
      if (Array.isArray(data.competitor_data) && data.competitor_data.length > 0) {
        loadedCompetitors = data.competitor_data.map((c: any, idx: number) => ({
          id: `c${idx + 1}`,
          name: c.name || `Competitor ${idx + 1}`,
        }));
        data.competitor_data.forEach((c: any, idx: number) => {
          const cId = `c${idx + 1}`;
          if (c.values && typeof c.values === 'object') {
            Object.entries(c.values).forEach(([propName, val]) => {
              if (!loadedCompValues[propName]) loadedCompValues[propName] = {};
              loadedCompValues[propName][cId] = String(val);
            });
          }
        });
      }

      setStep1InputsState((prev) => ({
        targetProduct: data.target_product || prev.targetProduct,
        processType: loadedProcessType || prev.processType,
        temperatureMin: loadedTempMin !== '' ? loadedTempMin : prev.temperatureMin,
        temperatureMax: loadedTempMax !== '' ? loadedTempMax : prev.temperatureMax,
        temperatureUnit: loadedTempUnit || prev.temperatureUnit,
        desired: Object.keys(loadedDesired).length > 0 ? loadedDesired : prev.desired,
        competitors: loadedCompetitors.length > 0 ? loadedCompetitors : prev.competitors,
        competitorValues: Object.keys(loadedCompValues).length > 0 ? loadedCompValues : prev.competitorValues,
      }));

      // Set generation snapshot to match loaded cycle
      setGenerationState({
        hasGeneratedRecipes: cands.length > 0,
        generationContextSnapshot: {
          targetProduct: data.target_product || '',
          processType: loadedProcessType,
          temperatureMin: loadedTempMin,
          temperatureMax: loadedTempMax,
          desiredJson: JSON.stringify(loadedDesired),
          competitorValuesJson: JSON.stringify(loadedCompValues),
          reportId: data.research_run_id || null,
        },
        inputsChangedSinceGeneration: false,
      });

      setCycleId(id);
    } catch (err: any) {
      setError(err.message || "Failed to load recipe cycle");
      if (err.message && err.message.includes("404")) resetContext();
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Discard any leftover demo session id from localStorage
    if (cycleId?.includes("demo")) {
      resetContext();
      return;
    }
    if (cycleId && !cycle && !loading && !cycleId.includes("demo")) {
      loadCycle(cycleId);
    }
  }, [cycleId]);

  const createCycle = async (payload: any) => {
    setLoading(true);
    setError(null);
    // Clear stale candidates and selections before new cycle creation
    setCandidates([]);
    setSelectedCandidate(null);
    trialRef.current = null;
    setTrial(null);
    setOptimizedCandidates([]);
    setSelectedOptimized(null);
    try {
      const newCycle = await api.createRecipeCycle(payload);
      cycleIdRef.current = newCycle.id;
      setCycle(newCycle);
      setCycleId(newCycle.id);
      return newCycle.id;
    } catch (err: any) {
      setError(err.message || "Failed to create recipe cycle");
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const updateCycle = async (payload: any) => {
    const activeId = cycleIdRef.current || cycleId;
    if (!activeId) return;
    setLoading(true);
    setError(null);
    try {
      const updated = await api.updateRecipeCycle(activeId, payload);
      setCycle(updated);
    } catch (err: any) {
      setError(err.message || "Failed to update recipe cycle");
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const generateRecipes = async (targetCycleId?: string) => {
    const activeId = targetCycleId || cycleIdRef.current || cycleId;
    if (!activeId) {
      const msg = "No active recipe cycle ID for generation";
      setError(msg);
      throw new Error(msg);
    }
    setGenerating(true);
    setCandidates([]); // Clear stale candidates before generation starts
    setError(null);
    try {
      const cands = await api.generateRecipes(activeId);
      setCandidates(cands || []);
      const updated = await api.getRecipeCycle(activeId);
      setCycle(updated);
      setGenerationState((prev) => ({
        ...prev,
        hasGeneratedRecipes: true,
        inputsChangedSinceGeneration: false,
      }));
    } catch (err: any) {
      setError(err.message || "Failed to generate recipes");
      throw err;
    } finally {
      setGenerating(false);
    }
  };

  const selectCandidate = async (candidateId: string) => {
    const activeId = cycleIdRef.current || cycleId;
    if (!activeId) return;
    setLoading(true);
    setError(null);
    try {
      const updatedCycle = await api.selectCandidate(activeId, candidateId);
      setCycle(updatedCycle);

      const updatedCandidates = candidates.map((c) => ({
        ...c,
        is_selected: c.id === candidateId,
      }));
      setCandidates(updatedCandidates);

      const sel = updatedCandidates.find((c) => c.id === candidateId);
      setSelectedCandidate(sel || null);
    } catch (err: any) {
      setError(err.message || "Failed to select candidate");
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const createTrial = async (payload: any) => {
    setLoading(true);
    setError(null);
    try {
      const body: any = {
        feedback_text: payload.feedback_text ?? payload.feedback ?? null,
        actual_values: payload.actual_values ?? payload.measured_values ?? {},
        target_values: payload.target_values ?? {},
      };

      if (payload.saved_recipe_id) {
        body.saved_recipe_id = payload.saved_recipe_id;
      } else {
        body.selected_candidate_id =
          payload.selected_candidate_id || selectedCandidate?.id;
      }

      if (!body.saved_recipe_id && !body.selected_candidate_id) {
        throw new Error("Provide a saved recipe or selected candidate for trial");
      }

      const newTrial = await api.createCustomerTrial(body);
      trialRef.current = newTrial;
      setTrial(newTrial);
      setOptimizedCandidates([]);
      setSelectedOptimized(null);

      if (cycle && body.selected_candidate_id) {
        setCycle({ ...cycle, status: "STEP3" });
      }
      return newTrial;
    } catch (err: any) {
      setError(err.message || "Failed to create trial");
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const updateTrial = async (payload: any) => {
    if (!trial) return;
    setLoading(true);
    setError(null);
    try {
      const updated = await api.updateCustomerTrial(trial.id, payload);
      setTrial(updated);
    } catch (err: any) {
      setError(err.message || "Failed to update trial");
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const generateOptimization = async () => {
    const activeTrial = trialRef.current || trial;
    if (!activeTrial) {
      throw new Error("Submit trial feedback before generating revisions");
    }
    setOptimizing(true);
    setError(null);
    try {
      const opts = await api.generateOptimization(activeTrial.id);
      setOptimizedCandidates(opts || []);
      const completed = { ...activeTrial, status: "COMPLETED", optimized_candidates: opts || [] };
      trialRef.current = completed;
      setTrial(completed);

      if (cycle) {
        setCycle({ ...cycle, status: "STEP4" });
      }
    } catch (err: any) {
      if (isRecipeDemoMode()) {
        const comp =
          (activeTrial as any)?.recipe_snapshot?.compound ||
          (activeTrial as any)?.compound ||
          selectedCandidate?.recipe_data?.compound ||
          "Demo Polymer";
        const targets = (activeTrial as any)?.target_values || [];
        const targetsList = Array.isArray(targets)
          ? targets
          : Object.entries(targets).map(([k, v]) => ({ name: k, target: v }));
        const demoRevisions = getDemoRevisedRecipes(
          (activeTrial as any)?.recipe_snapshot?.recipe_name || "Base Recipe",
          comp,
          {
            processType: (activeTrial as any)?.recipe_snapshot?.process_conditions?.process_type || "Batch",
            tempRange: (activeTrial as any)?.recipe_snapshot?.process_conditions?.temperature_range,
          },
          targetsList
        );
        setOptimizedCandidates(demoRevisions);
        const completed = { ...activeTrial, status: "COMPLETED", optimized_candidates: demoRevisions };
        trialRef.current = completed;
        setTrial(completed);
        return;
      }
      setError(err.message || "Failed to generate optimization");
      throw err;
    } finally {
      setOptimizing(false);
    }
  };

  const selectOptimized = async (optimizedId: string) => {
    if (!trial) return;
    setLoading(true);
    setError(null);
    try {
      const updatedTrial = await api.selectOptimized(trial.id, optimizedId);
      trialRef.current = updatedTrial;
      setTrial(updatedTrial);

      const updatedOpts = (trial.optimized_candidates || optimizedCandidates).map((o: any) => ({
        ...o,
        is_selected: o.id === optimizedId,
      }));
      setOptimizedCandidates(updatedOpts);

      const sel = updatedOpts.find((o: any) => o.id === optimizedId);
      setSelectedOptimized(sel || null);

      if (cycle) {
        setCycle({ ...cycle, status: "COMPLETED" });
      }
    } catch (err: any) {
      setError(err.message || "Failed to select optimized candidate");
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const loadTrial = async (trialId: string) => {
    setLoading(true);
    setError(null);
    try {
      const trialData = await api.getCustomerTrial(trialId);
      trialRef.current = trialData;
      setTrial(trialData);
      const opts = await api.getOptimizedCandidates(trialId);
      setOptimizedCandidates(opts || []);
      const selOpt = (opts || []).find((o: any) => o.is_selected);
      setSelectedOptimized(selOpt || null);
      return { trial: trialData, candidates: opts };
    } catch (err: any) {
      console.warn("Could not load trial session:", err);
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const saveSavedRecipe = async (payload: any) => {
    setLoading(true);
    setError(null);
    try {
      const body = { ...payload };
      return await api.createSavedRecipe(body);
    } catch (err: any) {
      setError(err.message || "Failed to save recipe");
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const updateCandidateRecipeData = async (
    candidateId: string,
    payload: { recipe_data: any; name?: string }
  ) => {
    const activeId = cycleIdRef.current || cycleId;
    if (!activeId) throw new Error("No active cycle");
    setLoading(true);
    setError(null);
    try {
      const updated = await api.updateCandidateRecipe(activeId, candidateId, payload);
      setCandidates((prev) =>
        prev.map((c) => (c.id === candidateId ? { ...c, ...updated } : c))
      );
      if (selectedCandidate?.id === candidateId) {
        setSelectedCandidate({ ...selectedCandidate, ...updated });
      }
      return updated;
    } catch (err: any) {
      setError(err.message || "Failed to update candidate");
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const updateOptimizedCandidateData = async (
    candidateId: string,
    payload: { recipe_data: any; name?: string }
  ) => {
    const activeTrial = trialRef.current || trial;
    if (!activeTrial) throw new Error("No active trial");
    setLoading(true);
    setError(null);
    try {
      const updated = await api.updateOptimizedCandidateRecipe(
        activeTrial.id,
        candidateId,
        payload
      );
      setOptimizedCandidates((prev) =>
        prev.map((c) => (c.id === candidateId ? { ...c, ...updated } : c))
      );
      if (selectedOptimized?.id === candidateId) {
        setSelectedOptimized({ ...selectedOptimized, ...updated });
      }
      return updated;
    } catch (err: any) {
      setError(err.message || "Failed to update optimized candidate");
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const value: RecipeContextType = {
    cycleId,
    cycle,
    candidates,
    selectedCandidate,
    trial,
    optimizedCandidates,
    selectedOptimized,
    loading,
    generating,
    optimizing,
    error,
    demoMode: isRecipeDemoMode(),
    generationState,
    step1Inputs,
    setStep1Inputs,
    setGenerationSnapshot,
    markInputsChanged,
    resetGenerationSession,
    updateCandidateLocally,
    setCycleId,
    clearError,
    loadDemoSession,
    loadCycle,
    createCycle,
    updateCycle,
    generateRecipes,
    selectCandidate,
    createTrial,
    updateTrial,
    generateOptimization,
    selectOptimized,
    loadTrial,
    resetContext,
    saveSavedRecipe,
    updateCandidateRecipeData,
    updateOptimizedCandidateData,
  };

  return <RecipeContext.Provider value={value}>{children}</RecipeContext.Provider>;
}

export function useRecipe() {
  const context = useContext(RecipeContext);
  if (context === undefined) {
    throw new Error('useRecipe must be used within a RecipeProvider');
  }
  return context;
}
