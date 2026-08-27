import { useState } from "react";
import { RefreshCw, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ProjectOverview } from "@/types";

interface CourseEpisodeOverviewCardProps {
  overview: ProjectOverview;
  onRegenerate?: () => Promise<void>;
}

export function CourseEpisodeOverviewCard({
  overview,
  onRegenerate,
}: CourseEpisodeOverviewCardProps) {
  const { t } = useTranslation("dashboard");
  const [regenerating, setRegenerating] = useState(false);

  const regenerate = async () => {
    if (!onRegenerate || regenerating) return;
    setRegenerating(true);
    try {
      await onRegenerate();
    } catch {
      // 调用方负责错误提示；概述卡保留现有成功结果。
    } finally {
      setRegenerating(false);
    }
  };

  return (
    <section
      aria-labelledby="course-episode-overview-heading"
      className="mb-5 rounded-xl border border-[var(--color-hairline-soft)] bg-[oklch(0.21_0.012_265/0.62)] p-5 shadow-[0_10px_30px_-20px_oklch(0_0_0/0.8)]"
    >
      <div className="mb-3 flex items-center gap-2.5">
        <Sparkles className="h-4 w-4 text-[var(--color-accent-2)]" aria-hidden="true" />
        <h2
          id="course-episode-overview-heading"
          className="text-[12px] font-bold uppercase tracking-[0.08em] text-[var(--color-text-3)]"
        >
          {t("course_episode_overview_title")}
        </h2>
        <span className="flex-1" />
        {onRegenerate && (
          <button
            type="button"
            onClick={() => void regenerate()}
            disabled={regenerating}
            className="focus-ring inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-[var(--color-text-3)] transition-colors hover:bg-white/5 hover:text-[var(--color-text)] disabled:cursor-wait disabled:opacity-60"
          >
            <RefreshCw
              className={`h-3 w-3 ${regenerating ? "motion-safe:animate-spin" : ""}`}
              aria-hidden="true"
            />
            {regenerating ? t("regenerating_short") : t("regen_short")}
          </button>
        )}
      </div>

      <div className="space-y-4">
        <div>
          <h3 className="mb-1 text-[11px] font-medium text-[var(--color-text-4)]">
            {t("synopsis_label")}
          </h3>
          <p className="text-[13px] leading-6 text-[var(--color-text-2)]">{overview.synopsis}</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          {[
            [t("genre_label"), overview.genre],
            [t("theme_label"), overview.theme],
            [t("world_setting_label"), overview.world_setting],
          ].map(([label, value]) => (
            <div
              key={label}
              className="rounded-lg border border-[var(--color-hairline-soft)] bg-black/10 px-3 py-2.5"
            >
              <h3 className="text-[10.5px] font-medium text-[var(--color-text-4)]">{label}</h3>
              <p className="mt-1 text-[12px] leading-5 text-[var(--color-text-2)]">{value}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
