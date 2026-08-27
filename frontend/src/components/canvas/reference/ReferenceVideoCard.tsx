import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { MentionTextarea } from "./MentionTextarea";
import { buildMentionCandidates } from "./mention-candidates";
import { buildMentionLookup, normalizeAssetName } from "@/utils/reference-mentions";
import { useProjectsStore } from "@/stores/projects-store";
import type { ReferenceVideoUnit } from "@/types/reference-video";

export interface ReferenceVideoCardProps {
  unit: ReferenceVideoUnit;
  projectName: string;
  episode: number;
  /** Controlled value — parent owns the draft/saved state. */
  value: string;
  /** Fires on every edit; parent decides whether to debounce, persist, or queue. */
  onChange: (next: string) => void;
  /** Image descriptions share the same asset picker but do not reference sibling Keyframes. */
  includeKeyframes?: boolean;
  showMeta?: boolean;
  /** Course units expose their workflow-owned type as a read-only tag beside the unit ID. */
  showUnitType?: boolean;
  placeholder?: string;
  ariaLabel?: string;
  disabled?: boolean;
}

export function ReferenceVideoCard({
  unit,
  projectName,
  episode: _episode,
  value,
  onChange,
  includeKeyframes = true,
  showMeta = true,
  showUnitType = false,
  placeholder,
  ariaLabel,
  disabled = false,
}: ReferenceVideoCardProps) {
  const { t } = useTranslation("dashboard");
  const project = useProjectsStore((state) => state.currentProjectData);

  const lookup = useMemo(() => {
    const next = buildMentionLookup(project);
    if (includeKeyframes) {
      for (const keyframe of unit.keyframes ?? []) {
        next[normalizeAssetName(`关键分镜 ${keyframe.keyframe_id}`)] = "keyframe";
      }
    }
    return next;
  }, [includeKeyframes, project, unit.keyframes]);
  const candidates = useMemo(
    () => buildMentionCandidates(project, includeKeyframes ? unit.keyframes : []),
    [includeKeyframes, project, unit.keyframes],
  );

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col">
      {showMeta && (
        <div className="mb-1 flex items-center justify-between text-[11px] text-gray-500">
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="font-mono text-gray-400" translate="no">
              {unit.unit_id}
            </span>
            {showUnitType && unit.unit_type && (
              <span className="rounded-full border border-violet-400/20 bg-violet-500/10 px-2 py-0.5 text-[9px] font-medium tracking-wide text-violet-200">
                {t(`course_unit_${unit.unit_type}`)}
              </span>
            )}
          </span>
          <span className="tabular-nums text-gray-500">
            {t("reference_editor_unit_meta", { duration: unit.duration_seconds })}
          </span>
        </div>
      )}

      <MentionTextarea
        value={value}
        onChange={onChange}
        lookup={lookup}
        candidates={candidates}
        projectName={projectName}
        ariaLabel={ariaLabel ?? t("reference_editor_aria_name")}
        placeholder={placeholder ?? t("reference_editor_placeholder")}
        disabled={disabled}
        fill
        className="min-h-0 flex-1"
      />
    </div>
  );
}
