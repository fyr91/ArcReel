import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Clapperboard, Loader2, Trash2 } from "lucide-react";
import type { EpisodeMeta } from "@/types";
import { itemCountKey, type GenerationRoute } from "@/utils/generation-mode";
import { useCostStore } from "@/stores/cost-store";
import { totalBreakdown } from "@/utils/cost-format";

interface EpisodeCardProps {
  ep: EpisodeMeta;
  active: boolean;
  onClick: () => void;
  /** ad 项目隐藏集语义：徽标不显示 E{n}，改用场记板图标。 */
  showEpisodeBadge?: boolean;
  /** ep.title 为空时的兜底显示文本（ad 项目用项目标题）。 */
  fallbackTitle?: string;
  /** 项目生成路线：决定条目数报「分镜数」还是「视频单元数」。必填，漏接线时类型报错而不是静默显示错名词。 */
  route: GenerationRoute;
  /** 课程项目可删除独立分集；未提供时不渲染破坏性入口。 */
  onDelete?: () => void;
  deleteLabel?: string;
  deleting?: boolean;
  /** 双击标题后的保存回调；未提供时标题保持普通导航文本。 */
  onRename?: (title: string) => Promise<void>;
}

const STATUS_COLOR: Record<string, string> = {
  completed: "oklch(0.74 0.08 155)",
  in_production: "var(--color-accent)",
  scripted: "oklch(0.60 0.02 250)",
  draft: "oklch(0.46 0.01 250)",
  missing: "oklch(0.46 0.01 250)",
};

const STATUS_LABEL_KEY: Record<string, string> = {
  completed: "dashboard:episode_status_done",
  in_production: "dashboard:episode_status_active",
  scripted: "dashboard:episode_status_draft",
  draft: "dashboard:episode_status_draft",
  missing: "dashboard:episode_status_idea",
};

/**
 * 侧栏分集卡片：左缩略 (E1 字符) + 中标题/状态/进度 + 右费用。
 * Active 态有 accent 紫边框 + 玻璃面板背景。
 */
export function EpisodeCard({
  ep,
  active,
  onClick,
  showEpisodeBadge = true,
  fallbackTitle,
  route,
  onDelete,
  deleteLabel,
  deleting = false,
  onRename,
}: EpisodeCardProps) {
  const { t } = useTranslation(["dashboard"]);
  const status = ep.status ?? "draft";
  const statusColor = STATUS_COLOR[status] ?? STATUS_COLOR.draft;
  const statusLabel = t(STATUS_LABEL_KEY[status] ?? STATUS_LABEL_KEY.draft);
  const isActive = status === "in_production";
  const displayTitle = ep.title || fallbackTitle || "";
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState(displayTitle);
  const [savingTitle, setSavingTitle] = useState(false);
  const titleInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!editingTitle) return;
    titleInputRef.current?.focus();
    titleInputRef.current?.select();
  }, [editingTitle]);

  const startTitleEdit = () => {
    if (!onRename || savingTitle) return;
    setTitleDraft(displayTitle);
    setEditingTitle(true);
  };

  const cancelTitleEdit = () => {
    setTitleDraft(displayTitle);
    setEditingTitle(false);
  };

  const saveTitle = async () => {
    if (!onRename || savingTitle) return;
    const next = titleDraft.trim();
    if (!next) return;
    if (next === displayTitle) {
      setEditingTitle(false);
      return;
    }
    setSavingTitle(true);
    try {
      await onRename(next);
      setEditingTitle(false);
    } catch {
      // 调用方负责 toast；保留输入内容，方便用户修正或重试。
      requestAnimationFrame(() => titleInputRef.current?.focus());
    } finally {
      setSavingTitle(false);
    }
  };

  // 进度按视频产物的可用数算——可用 = current ∪ stale，与工作台同一份计数。
  // 视频总数为 0（尚未成脚本）时退回剧本条目数，只用于显示"这集有几件内容"。
  const videoTotal = ep.videos?.total ?? 0;
  const itemCount = ep.item_count ?? 0;
  const totalShots = videoTotal || itemCount;
  const itemCountLabel = t(itemCountKey(route), { count: itemCount });
  const availableVideos = ep.videos?.available ?? 0;
  const progress =
    videoTotal > 0 ? Math.round((availableVideos / videoTotal) * 100) : 0;
  const showProgress = videoTotal > 0 && (active || progress > 0);

  // stale 是可用产物，不进缺口计数：单独报一个数说明有几件可以考虑重生。
  // 汇总该集全部产物类型，与大厅卡片上那一行同口径。
  const staleCount = (ep.storyboards?.stale ?? 0) + (ep.videos?.stale ?? 0);

  // 实际费用
  const episodeCost = useCostStore((s) => s.getEpisodeCost(ep.episode));
  const spentBreakdown = episodeCost ? totalBreakdown(episodeCost.totals.actual) : null;
  // spentBreakdown 是 Record<currency, number>，取主要币种
  const spentEntries = spentBreakdown ? Object.entries(spentBreakdown).filter(([, v]) => v > 0) : [];
  const primaryCost = spentEntries.find(([c]) => c === "USD") ?? spentEntries[0];
  const costText = primaryCost
    ? `${primaryCost[0] === "CNY" ? "¥" : "$"}${primaryCost[1].toFixed(2)}`
    : null;

  // 时长格式化
  const dur = ep.duration_seconds ?? 0;
  const durLabel = dur > 0 ? `${Math.floor(dur / 60)}:${String(dur % 60).padStart(2, "0")}` : null;

  return (
    <div className="group relative w-full" style={{ marginBottom: 3 }}>
      <div
        className="grid w-full items-center gap-2.5 rounded-lg p-2 text-left transition-colors focus-ring"
        style={{
          gridTemplateColumns: "auto 1fr auto",
          paddingRight: onDelete ? 36 : undefined,
          background: active
            ? "linear-gradient(180deg, oklch(0.26 0.018 160 / 0.55), oklch(0.22 0.015 160 / 0.4))"
            : "transparent",
          border: active ? "1px solid var(--color-accent-soft)" : "1px solid transparent",
          boxShadow: active
            ? "0 0 0 1px var(--color-accent-soft), 0 4px 12px -6px oklch(0 0 0 / 0.5), inset 0 1px 0 oklch(1 0 0 / 0.04)"
            : "none",
        }}
        onMouseEnter={(e) => {
          if (!active) e.currentTarget.style.background = "oklch(0.24 0.012 265 / 0.4)";
        }}
        onMouseLeave={(e) => {
          if (!active) e.currentTarget.style.background = "transparent";
        }}
      >
        <button
          type="button"
          onClick={onClick}
          aria-label={displayTitle}
          className="focus-ring absolute inset-0 rounded-lg"
        />
        <div
          className="num pointer-events-none relative grid h-[34px] w-[34px] shrink-0 place-items-center rounded-md text-[11px] font-bold leading-none"
          style={{
            background: active
              ? "linear-gradient(135deg, var(--color-accent) 0%, oklch(0.45 0.12 160) 100%)"
              : "linear-gradient(180deg, oklch(0.28 0.013 265), oklch(0.24 0.012 265))",
            color: active ? "oklch(0.14 0 0)" : "var(--color-text-3)",
            boxShadow: active
              ? "inset 0 1px 0 oklch(1 0 0 / 0.25), 0 0 0 1px oklch(1 0 0 / 0.12), 0 2px 6px -2px var(--color-accent-glow)"
              : "inset 0 1px 0 oklch(1 0 0 / 0.04), inset 0 0 0 1px var(--color-hairline-soft)",
          }}
        >
          {showEpisodeBadge ? `E${ep.episode}` : <Clapperboard className="h-4 w-4" aria-hidden />}
        </div>

        <div className="pointer-events-none relative min-w-0">
        {editingTitle ? (
          <input
            ref={titleInputRef}
            value={titleDraft}
            onChange={(event) => setTitleDraft(event.target.value)}
            onClick={(event) => event.stopPropagation()}
            onDoubleClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => {
              event.stopPropagation();
              if (event.nativeEvent.isComposing) return;
              if (event.key === "Enter") {
                event.preventDefault();
                void saveTitle();
              } else if (event.key === "Escape") {
                event.preventDefault();
                cancelTitleEdit();
              }
            }}
            disabled={savingTitle}
            aria-label={t("edit_episode_title")}
            className="focus-ring pointer-events-auto block w-full min-w-0 rounded border border-[var(--color-accent-soft)] bg-[oklch(0.16_0.01_250/0.9)] px-1 py-0.5 text-[13px] outline-none disabled:opacity-60"
            style={{
              color: "var(--color-text)",
              fontWeight: active ? 600 : 500,
            }}
          />
        ) : (
          <button
            type="button"
            onClick={onClick}
            onDoubleClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              startTitleEdit();
            }}
            title={onRename ? t("edit_episode_title") : displayTitle}
            className="focus-ring pointer-events-auto block w-full truncate rounded-sm text-left text-[13px]"
            style={{
              color: active ? "var(--color-text)" : "var(--color-text-2)",
              fontWeight: active ? 600 : 500,
            }}
          >
            {displayTitle}
          </button>
        )}
        <div className="mt-[3px] flex items-center gap-1.5">
          <span
            className="inline-flex items-center gap-1 text-[10.5px]"
            style={{ color: "var(--color-text-4)" }}
          >
            <span
              className={`h-[5px] w-[5px] rounded-full ${
                isActive ? "animate-shot-pulse" : ""
              }`}
              style={{ background: statusColor }}
            />
            {statusLabel}
          </span>
          {totalShots > 0 && (
            <>
              <span
                aria-hidden="true"
                className="h-px w-px rounded"
                style={{ background: "var(--color-hairline)", width: 2, height: 2 }}
              />
              <span
                className="num text-[10.5px]"
                style={{ color: "var(--color-text-4)" }}
                title={
                  videoTotal > 0
                    ? t("episode_available_videos_hint", { count: availableVideos, total: videoTotal })
                    : undefined
                }
              >
                {videoTotal > 0 ? `${availableVideos}/${videoTotal}` : itemCountLabel}
                {durLabel ? ` · ${durLabel}` : ""}
              </span>
            </>
          )}
          {staleCount > 0 && (
            <span
              className="num inline-flex items-center gap-1 text-[10.5px] text-warm-bright"
              title={t("episode_stale_artifacts", { count: staleCount })}
            >
              <span
                aria-hidden
                className="h-[5px] w-[5px] rounded-full"
                style={{ background: "var(--color-warm-bright)" }}
              />
              <span aria-hidden>{staleCount}</span>
              <span className="sr-only">{t("episode_stale_artifacts", { count: staleCount })}</span>
            </span>
          )}
        </div>
        {showProgress && (
          <div
            className="mt-[5px] h-[2px] overflow-hidden rounded-[1px]"
            style={{ background: "oklch(0.22 0.010 265)" }}
          >
            <div
              className="h-full"
              style={{
                width: `${progress}%`,
                background: "linear-gradient(90deg, var(--color-accent), var(--color-accent-2))",
                boxShadow: "0 0 6px var(--color-accent-glow)",
              }}
            />
          </div>
        )}
        </div>

        {costText && (
          <span
            className="num pointer-events-none relative self-start pt-0.5 text-[10.5px]"
            style={{ color: active ? "var(--color-accent-2)" : "var(--color-text-4)" }}
          >
            {costText}
          </span>
        )}
      </div>
      {onDelete && deleteLabel && (
        <button
          type="button"
          onClick={onDelete}
          disabled={deleting}
          title={deleteLabel}
          aria-label={deleteLabel}
          className="focus-ring absolute bottom-1.5 right-1.5 z-10 grid h-6 w-6 place-items-center rounded-md opacity-65 transition-[opacity,background-color,color] hover:opacity-100 focus-visible:opacity-100 disabled:cursor-wait"
          style={{
            background: "oklch(0.22 0.02 25 / 0.82)",
            color: "var(--color-warm-bright)",
            border: "1px solid oklch(0.58 0.14 30 / 0.25)",
          }}
        >
          {deleting ? (
            <Loader2 className="h-3 w-3 motion-safe:animate-spin" aria-hidden />
          ) : (
            <Trash2 className="h-3 w-3" aria-hidden />
          )}
        </button>
      )}
    </div>
  );
}
