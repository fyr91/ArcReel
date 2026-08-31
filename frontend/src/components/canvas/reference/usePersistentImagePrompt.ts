import { useCallback, useEffect, useRef, useState } from "react";
import { useAppStore } from "@/stores/app-store";
import { errMsg } from "@/utils/async";

export type ImagePromptMode = "description" | "full_prompt";

export interface ImagePromptPersistencePatch {
  description?: string;
  mode?: ImagePromptMode;
  fullPrompt?: string | null;
}

interface UsePersistentImagePromptOptions {
  resourceId: string;
  savedMode?: ImagePromptMode;
  savedFullPrompt?: string | null;
  description: string;
  savedDescription: string;
  disabled: boolean;
  buildFullPrompt: (description: string) => Promise<string>;
  persist: (patch: ImagePromptPersistencePatch) => Promise<void>;
  onChanged: () => Promise<void>;
}

/** Keeps one resource's flip mode and editable full prompt durable across reloads. */
export function usePersistentImagePrompt({
  resourceId,
  savedMode = "description",
  savedFullPrompt,
  description,
  savedDescription,
  disabled,
  buildFullPrompt,
  persist,
  onChanged,
}: UsePersistentImagePromptOptions) {
  const [mode, setMode] = useState<ImagePromptMode>(savedMode);
  const [fullPrompt, setFullPrompt] = useState(savedFullPrompt ?? "");
  const [saving, setSaving] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const persistedFullPrompt = useRef(savedFullPrompt ?? "");
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearAutosave = useCallback(() => {
    if (autosaveTimer.current !== null) {
      clearTimeout(autosaveTimer.current);
      autosaveTimer.current = null;
    }
  }, []);

  useEffect(() => {
    clearAutosave();
    persistedFullPrompt.current = savedFullPrompt ?? "";
    // External edits and a page/project reload are authoritative for this resource.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMode(savedMode);
    setFullPrompt(savedFullPrompt ?? "");
  }, [clearAutosave, resourceId, savedFullPrompt, savedMode]);

  useEffect(() => {
    if (
      mode !== "full_prompt" ||
      disabled ||
      !fullPrompt.trim() ||
      fullPrompt === persistedFullPrompt.current
    ) {
      return;
    }
    clearAutosave();
    autosaveTimer.current = setTimeout(() => {
      const value = fullPrompt;
      setSaving(true);
      void persist({ fullPrompt: value })
        .then(() => {
          persistedFullPrompt.current = value;
        })
        .catch((error) => {
          useAppStore.getState().pushToast(errMsg(error), "error");
        })
        .finally(() => {
          autosaveTimer.current = null;
          setSaving(false);
        });
    }, 700);
    return clearAutosave;
  }, [clearAutosave, disabled, fullPrompt, mode, persist]);

  useEffect(() => clearAutosave, [clearAutosave]);

  const switchMode = useCallback(
    async (nextMode: ImagePromptMode) => {
      if (nextMode === mode || disabled || saving || preparing) return;
      clearAutosave();
      setPreparing(true);
      try {
        if (nextMode === "full_prompt") {
          const normalizedDescription = description.trim();
          if (!normalizedDescription) return;
          const prompt = fullPrompt.trim()
            ? fullPrompt
            : await buildFullPrompt(normalizedDescription);
          await persist({
            ...(normalizedDescription !== savedDescription ? { description: normalizedDescription } : {}),
            mode: "full_prompt",
            fullPrompt: prompt,
          });
          persistedFullPrompt.current = prompt;
          setFullPrompt(prompt);
        } else {
          const pendingPrompt = fullPrompt.trim() ? fullPrompt : null;
          await persist({
            mode: "description",
            ...(pendingPrompt !== persistedFullPrompt.current ? { fullPrompt: pendingPrompt } : {}),
          });
          if (pendingPrompt !== null) persistedFullPrompt.current = pendingPrompt;
        }
        setMode(nextMode);
        await onChanged();
      } catch (error) {
        useAppStore.getState().pushToast(errMsg(error), "error");
      } finally {
        setPreparing(false);
      }
    }, [
      buildFullPrompt,
      clearAutosave,
      description,
      disabled,
      fullPrompt,
      mode,
      onChanged,
      persist,
      preparing,
      savedDescription,
      saving,
    ],
  );

  const saveBeforeGenerate = useCallback(async (): Promise<boolean> => {
    if (disabled || saving || preparing) return false;
    clearAutosave();
    setSaving(true);
    try {
      if (mode === "full_prompt") {
        if (!fullPrompt.trim()) return false;
        await persist({ mode, fullPrompt });
        persistedFullPrompt.current = fullPrompt;
      } else {
        const normalizedDescription = description.trim();
        if (!normalizedDescription) return false;
        if (normalizedDescription !== savedDescription) {
          await persist({ description: normalizedDescription });
        }
      }
      await onChanged();
      return true;
    } catch (error) {
      useAppStore.getState().pushToast(errMsg(error), "error");
      return false;
    } finally {
      setSaving(false);
    }
  }, [
    clearAutosave,
    description,
    disabled,
    fullPrompt,
    mode,
    onChanged,
    persist,
    preparing,
    savedDescription,
    saving,
  ]);

  return {
    mode,
    fullPrompt,
    setFullPrompt,
    saving,
    preparing,
    switchMode,
    saveBeforeGenerate,
  };
}
