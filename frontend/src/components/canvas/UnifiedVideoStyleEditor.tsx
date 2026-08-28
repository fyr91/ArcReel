import { useId, useState } from "react";
import { Save, Video } from "lucide-react";
import { useTranslation } from "react-i18next";

import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import type { UnifiedVideoStyle } from "@/types";
import { errMsg } from "@/utils/async";

interface UnifiedVideoStyleEditorProps {
  projectName: string;
  videoStyle?: UnifiedVideoStyle | null;
  readOnly?: boolean;
}

export function UnifiedVideoStyleEditor({
  projectName,
  videoStyle,
  readOnly = false,
}: UnifiedVideoStyleEditorProps) {
  return (
    <UnifiedVideoStyleEditorForm
      key={`${projectName}:${videoStyle?.updated_at ?? "missing"}`}
      projectName={projectName}
      videoStyle={videoStyle}
      readOnly={readOnly}
    />
  );
}

function UnifiedVideoStyleEditorForm({
  projectName,
  videoStyle,
  readOnly = false,
}: UnifiedVideoStyleEditorProps) {
  const { t } = useTranslation(["dashboard", "common"]);
  const fieldId = useId();
  const [draft, setDraft] = useState(videoStyle?.prompt ?? "");
  const [saving, setSaving] = useState(false);

  const normalized = draft.trim();
  const dirty = normalized !== (videoStyle?.prompt ?? "");

  const save = async () => {
    if (!normalized || !dirty || saving || readOnly) return;
    setSaving(true);
    try {
      const result = await API.updateVideoStyle(projectName, { prompt: normalized });
      setDraft(result.video_style.prompt);
      await useProjectsStore.getState().refreshProject(projectName);
      useAppStore.getState().pushToast(t("dashboard:video_style_saved"), "success");
    } catch (error) {
      useAppStore.getState().pushToast(
        t("dashboard:video_style_save_failed", { message: errMsg(error) }),
        "error",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="rounded-xl border border-[var(--color-hairline-soft)] bg-[oklch(0.20_0.012_265/0.5)] p-5">
      <div className="flex items-start gap-2.5">
        <Video className="mt-0.5 h-4 w-4 text-[var(--color-accent-2)]" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[12px] font-bold uppercase tracking-[0.08em] text-[var(--color-text-3)]">
              {t("dashboard:video_style_section_title")}
            </h2>
            {videoStyle && (
              <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10.5px] text-emerald-300">
                {videoStyle.source === "agent"
                  ? t("dashboard:video_style_source_agent")
                  : t("dashboard:video_style_source_user")}
              </span>
            )}
          </div>
          <p className="mt-1 text-[11px] leading-5 text-[var(--color-text-4)]">
            {t("dashboard:video_style_section_description")}
          </p>
        </div>
      </div>

      <label htmlFor={fieldId} className="mt-4 block text-[11px] font-medium text-[var(--color-text-4)]">
        {t("dashboard:video_style_prompt")}
      </label>
      <textarea
        id={fieldId}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        disabled={saving || readOnly}
        rows={4}
        placeholder={t("dashboard:video_style_prompt_placeholder")}
        className="focus-ring mt-1.5 w-full resize-y rounded-lg border border-[var(--color-hairline)] bg-black/15 px-3 py-2 text-[13px] leading-6 text-[var(--color-text-2)] outline-none disabled:opacity-60"
      />
      <div className="mt-2 flex flex-wrap items-center gap-3">
        {!readOnly && (
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving || !normalized || !dirty}
            className="focus-ring inline-flex items-center gap-1.5 rounded-md bg-[var(--color-accent)] px-3 py-1.5 text-[12px] font-semibold text-black transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" aria-hidden="true" />
            {saving ? t("common:saving") : t("dashboard:video_style_save")}
          </button>
        )}
        <span className="text-[11px] leading-5 text-[var(--color-text-4)]">
          {videoStyle
            ? t("dashboard:analysis_video_style_shared_hint")
            : t("dashboard:analysis_video_style_missing_hint")}
        </span>
      </div>
    </section>
  );
}
