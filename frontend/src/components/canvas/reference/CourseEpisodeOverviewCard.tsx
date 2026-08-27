import { useId, useState } from "react";
import { CheckCircle2, Pencil, RefreshCw, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ProjectOverview } from "@/types";

interface CourseEpisodeOverviewCardProps {
  overview: ProjectOverview;
  status?: "draft" | "confirmed";
  onConfirm?: (overview: ProjectOverview) => Promise<void>;
  onRegenerate?: () => Promise<void>;
}

const INPUT_CLASS =
  "focus-ring mt-1.5 w-full rounded-lg border border-[var(--color-hairline)] bg-black/15 px-3 py-2 text-[13px] leading-6 text-[var(--color-text-2)] outline-none disabled:opacity-60";

function overviewDraft(overview: ProjectOverview): ProjectOverview {
  return {
    synopsis: overview.synopsis ?? "",
    genre: overview.genre ?? "",
    theme: overview.theme ?? "",
    world_setting: overview.world_setting ?? "",
  };
}

export function CourseEpisodeOverviewCard({
  overview,
  status = "confirmed",
  onConfirm,
  onRegenerate,
}: CourseEpisodeOverviewCardProps) {
  const { t } = useTranslation(["dashboard", "common"]);
  const [editing, setEditing] = useState(status === "draft");
  const [draft, setDraft] = useState(() => overviewDraft(overview));
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const synopsisId = useId();
  const genreId = useId();
  const themeId = useId();
  const worldId = useId();

  const confirm = async () => {
    if (!onConfirm || saving || regenerating) return;
    const normalized = {
      synopsis: draft.synopsis.trim(),
      genre: draft.genre.trim(),
      theme: draft.theme.trim(),
      world_setting: draft.world_setting.trim(),
    };
    if (!normalized.synopsis) return;
    setSaving(true);
    try {
      await onConfirm(normalized);
      setEditing(false);
    } catch {
      // 调用方负责 toast；保留用户输入以便修正或重试。
    } finally {
      setSaving(false);
    }
  };

  const regenerate = async () => {
    if (!onRegenerate || regenerating || saving) return;
    setRegenerating(true);
    try {
      await onRegenerate();
    } catch {
      // 调用方负责错误提示；失败时保留当前概述和编辑内容。
    } finally {
      setRegenerating(false);
    }
  };

  return (
    <section
      aria-labelledby="course-episode-overview-heading"
      aria-busy={saving || regenerating}
      className="rounded-xl border border-[var(--color-hairline-soft)] bg-[oklch(0.21_0.012_265/0.62)] p-5 shadow-[0_10px_30px_-20px_oklch(0_0_0/0.8)]"
    >
      <div className="mb-4 flex items-center gap-2.5">
        <Sparkles className="h-4 w-4 text-[var(--color-accent-2)]" aria-hidden="true" />
        <h2
          id="course-episode-overview-heading"
          className="text-[12px] font-bold uppercase tracking-[0.08em] text-[var(--color-text-3)]"
        >
          {t("dashboard:course_episode_overview_title")}
        </h2>
        <span
          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] ${
            status === "draft"
              ? "bg-amber-500/10 text-amber-300"
              : "bg-emerald-500/10 text-emerald-300"
          }`}
        >
          {status === "draft"
            ? t("dashboard:course_episode_analysis_draft")
            : t("dashboard:course_episode_analysis_confirmed")}
        </span>
        <span className="flex-1" />
        {!editing && onConfirm && (
          <button
            type="button"
            onClick={() => {
              setDraft(overviewDraft(overview));
              setEditing(true);
            }}
            disabled={regenerating}
            className="focus-ring inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-[var(--color-text-3)] transition-colors hover:bg-white/5 hover:text-[var(--color-text)] disabled:opacity-60"
          >
            <Pencil className="h-3 w-3" aria-hidden="true" />
            {t("dashboard:edit_overview")}
          </button>
        )}
        {onRegenerate && (
          <button
            type="button"
            onClick={() => void regenerate()}
            disabled={regenerating || saving}
            className="focus-ring inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-[var(--color-text-3)] transition-colors hover:bg-white/5 hover:text-[var(--color-text)] disabled:cursor-wait disabled:opacity-60"
          >
            <RefreshCw
              className={`h-3 w-3 ${regenerating ? "motion-safe:animate-spin" : ""}`}
              aria-hidden="true"
            />
            {regenerating ? t("dashboard:regenerating_short") : t("dashboard:regen_short")}
          </button>
        )}
      </div>

      {editing && onConfirm ? (
        <div className="space-y-3">
          <div>
            <label
              htmlFor={synopsisId}
              className="text-[11px] font-medium text-[var(--color-text-4)]"
            >
              {t("dashboard:synopsis_label")}
            </label>
            <textarea
              id={synopsisId}
              value={draft.synopsis}
              onChange={(event) =>
                setDraft((current) => ({ ...current, synopsis: event.target.value }))
              }
              disabled={saving || regenerating}
              rows={5}
              className={`${INPUT_CLASS} resize-y`}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label
                htmlFor={genreId}
                className="text-[11px] font-medium text-[var(--color-text-4)]"
              >
                {t("dashboard:genre_label")}
              </label>
              <input
                id={genreId}
                value={draft.genre}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, genre: event.target.value }))
                }
                disabled={saving || regenerating}
                className={INPUT_CLASS}
              />
            </div>
            <div>
              <label
                htmlFor={themeId}
                className="text-[11px] font-medium text-[var(--color-text-4)]"
              >
                {t("dashboard:theme_label")}
              </label>
              <input
                id={themeId}
                value={draft.theme}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, theme: event.target.value }))
                }
                disabled={saving || regenerating}
                className={INPUT_CLASS}
              />
            </div>
          </div>
          <div>
            <label
              htmlFor={worldId}
              className="text-[11px] font-medium text-[var(--color-text-4)]"
            >
              {t("dashboard:world_setting_label")}
            </label>
            <textarea
              id={worldId}
              value={draft.world_setting}
              onChange={(event) =>
                setDraft((current) => ({ ...current, world_setting: event.target.value }))
              }
              disabled={saving || regenerating}
              rows={3}
              className={`${INPUT_CLASS} resize-y`}
            />
          </div>
          <div className="flex items-center gap-2 pt-1">
            <button
              type="button"
              onClick={() => void confirm()}
              disabled={saving || regenerating || !draft.synopsis.trim()}
              className="focus-ring inline-flex items-center gap-1.5 rounded-md bg-[var(--color-accent)] px-3 py-1.5 text-[12px] font-semibold text-black transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
            >
              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
              {saving
                ? t("common:saving")
                : t("dashboard:course_episode_save_and_confirm")}
            </button>
            {status === "confirmed" && (
              <button
                type="button"
                onClick={() => {
                  setDraft(overviewDraft(overview));
                  setEditing(false);
                }}
                disabled={saving || regenerating}
                className="focus-ring rounded-md px-3 py-1.5 text-[12px] text-[var(--color-text-3)] hover:text-[var(--color-text)] disabled:opacity-50"
              >
                {t("common:cancel")}
              </button>
            )}
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div>
            <h3 className="mb-1 text-[11px] font-medium text-[var(--color-text-4)]">
              {t("dashboard:synopsis_label")}
            </h3>
            <p className="text-[13px] leading-6 text-[var(--color-text-2)]">
              {overview.synopsis}
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            {[
              [t("dashboard:genre_label"), overview.genre],
              [t("dashboard:theme_label"), overview.theme],
              [t("dashboard:world_setting_label"), overview.world_setting],
            ].map(([label, value]) => (
              <div
                key={label}
                className="rounded-lg border border-[var(--color-hairline-soft)] bg-black/10 px-3 py-2.5"
              >
                <h3 className="text-[10.5px] font-medium text-[var(--color-text-4)]">
                  {label}
                </h3>
                <p className="mt-1 text-[12px] leading-5 text-[var(--color-text-2)]">
                  {value}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
