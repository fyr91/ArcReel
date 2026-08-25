import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Images, Loader2, Save } from "lucide-react";
import { enqueueReferenceStoryboardSheet } from "@/actions/generation";
import { API } from "@/api";
import { ImageEditButton } from "@/components/canvas/timeline/ImageEditButton";
import { ReferenceVideoCard } from "@/components/canvas/reference/ReferenceVideoCard";
import { VersionTimeMachine } from "@/components/canvas/timeline/VersionTimeMachine";
import { ImageModelSelect, imageSelectionFromValue } from "@/components/shared/ImageModelSelect";
import { GenerateButton } from "@/components/ui/GenerateButton";
import { PreviewableImageFrame } from "@/components/ui/PreviewableImageFrame";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import { useActiveResourceIds } from "@/stores/tasks-store";
import { errMsg } from "@/utils/async";
import type { ReferenceVideoUnit } from "@/types";

function defaultStoryboardDescription(unit: ReferenceVideoUnit): string {
  return (
    unit.storyboard_description ?? unit.text.replace(/@\[关键分镜 [^\]]+\]\s*/g, "").trim()
  );
}

interface StoryboardSheetPanelProps {
  projectName: string;
  episode: number;
  unit: ReferenceVideoUnit;
  scriptFile?: string;
  onChanged: () => Promise<void>;
}

export function StoryboardSheetPanel({
  projectName,
  episode,
  unit,
  scriptFile,
  onChanged,
}: StoryboardSheetPanelProps) {
  const { t } = useTranslation("dashboard");
  const [model, setModel] = useState("");
  const [description, setDescription] = useState(() => defaultStoryboardDescription(unit));
  const [saving, setSaving] = useState(false);
  const activeIds = useActiveResourceIds("reference_storyboard_sheet", projectName);
  const busy = activeIds.has(unit.unit_id);
  const sheet = unit.storyboard_sheet;
  const fingerprint = useProjectsStore((state) =>
    sheet?.image_path ? state.getAssetFingerprint(sheet.image_path) : null,
  );
  const imageUrl = sheet?.image_path
    ? API.getFileUrl(projectName, sheet.image_path, fingerprint)
    : null;
  const savedDescription = defaultStoryboardDescription(unit);
  const dirty = description.trim() !== savedDescription;

  useEffect(() => {
    setDescription(defaultStoryboardDescription(unit));
  }, [unit.storyboard_description, unit.text]);

  const generate = async () => {
    try {
      await enqueueReferenceStoryboardSheet(
        projectName,
        episode,
        unit.unit_id,
        imageSelectionFromValue(model),
      );
    } catch (error) {
      useAppStore.getState().pushToast(errMsg(error), "error");
    }
  };

  const save = async () => {
    const next = description.trim();
    if (!next || !dirty || saving || busy) return;
    setSaving(true);
    try {
      await API.patchReferenceVideoUnit(projectName, episode, unit.unit_id, {
        storyboard_description: next,
      });
      await onChanged();
    } catch (error) {
      useAppStore.getState().pushToast(errMsg(error), "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      <article className="rounded-xl border border-[var(--color-hairline-soft)] bg-[oklch(0.20_0.011_265_/_0.55)] p-4">
        <header className="mb-3 flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-md border border-[var(--color-accent-soft)] bg-[var(--color-accent-dim)] text-[var(--color-accent-2)]">
            <Images className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
          <strong className="text-[13px] text-[var(--color-text)]">
            {t("reference_storyboard_sheet_title")}
          </strong>
          <span className="flex-1" />
          <ImageEditButton
            projectName={projectName}
            resourceType="reference_storyboard_sheet"
            resourceId={unit.unit_id}
            scriptFile={scriptFile}
            hasImage={Boolean(sheet?.image_path)}
            busy={busy}
          />
          <VersionTimeMachine
            projectName={projectName}
            resourceType="storyboard_sheets"
            resourceId={unit.unit_id}
            iconOnly
            busy={busy}
            onRestore={onChanged}
          />
        </header>

        {sheet?.generation_input_changed && (
          <p className="mb-3 flex items-start gap-2 rounded-lg border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-xs leading-5 text-amber-200">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            {t("reference_storyboard_sheet_manuscript_changed_hint")}
          </p>
        )}

        {imageUrl ? (
          <PreviewableImageFrame src={imageUrl} alt={t("reference_storyboard_sheet_title")}>
            <img
              src={imageUrl}
              alt={t("reference_storyboard_sheet_title")}
              loading="lazy"
              className="max-h-[70vh] w-full rounded-lg object-contain"
            />
          </PreviewableImageFrame>
        ) : (
          <div className="flex min-h-64 items-center justify-center rounded-lg border border-dashed border-[var(--color-hairline)] text-center text-xs text-[var(--color-text-4)]">
            {busy ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                {t("reference_storyboard_sheet_generating")}
              </span>
            ) : (
              t("reference_storyboard_sheet_not_generated")
            )}
          </div>
        )}

        <p className="mt-3 text-xs leading-5 text-[var(--color-text-3)]">
          {t("reference_storyboard_sheet_help")}
        </p>

        <div className="mt-3 text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--color-text-4)]">
          {t("reference_storyboard_sheet_description")}
          <div className="mt-1.5 h-56 min-h-56 shrink-0 normal-case tracking-normal">
            <ReferenceVideoCard
              unit={unit}
              projectName={projectName}
              episode={episode}
              value={description}
              onChange={setDescription}
              includeKeyframes={false}
              showMeta={false}
              placeholder={t("reference_storyboard_sheet_description_placeholder")}
              ariaLabel={t("reference_storyboard_sheet_description")}
              disabled={busy}
            />
          </div>
        </div>
        {dirty && (
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving || busy || !description.trim()}
            className="focus-ring mt-2 inline-flex items-center gap-1.5 rounded-md border border-[var(--color-hairline)] px-2.5 py-1 text-xs text-[var(--color-text-2)] disabled:opacity-40"
          >
            <Save className="h-3.5 w-3.5" aria-hidden="true" />
            {t("common:save")}
          </button>
        )}

        <div className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
          <ImageModelSelect value={model} onChange={setModel} capability="any" />
          <GenerateButton
            onClick={() => void generate()}
            loading={busy}
            label={
              sheet
                ? t("reference_storyboard_sheet_regenerate")
                : t("reference_storyboard_sheet_generate")
            }
            className="justify-center"
          />
        </div>

      </article>
    </div>
  );
}
