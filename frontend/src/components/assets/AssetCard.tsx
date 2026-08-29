import { memo } from "react";
import { useTranslation } from "react-i18next";
import { CloudUpload, Edit2, Trash2, User as UserIcon, Landmark, Package } from "lucide-react";
import { API } from "@/api";
import { formatDate } from "@/utils/date-format";
import type { Asset } from "@/types/asset";
import { AssetThumb } from "./AssetThumb";

interface Props {
  asset: Asset;
  onEdit: (asset: Asset) => void;
  onDelete: (asset: Asset) => void;
  onShare?: (asset: Asset) => void;
  sharing?: boolean;
}

const TYPE_ICON = { character: UserIcon, scene: Landmark, prop: Package };

const SHORT_DATE_OPTS: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };

export const AssetCard = memo(AssetCardImpl);

function AssetCardImpl({ asset, onEdit, onDelete, onShare, sharing = false }: Props) {
  const { t, i18n } = useTranslation("assets");
  const Icon = TYPE_ICON[asset.type];
  const imageUrl = API.getGlobalAssetUrl(asset.image_path, asset.updated_at);
  const formattedDate = asset.updated_at
    ? formatDate(asset.updated_at, i18n.language, SHORT_DATE_OPTS, "")
    : "";
  const publishState = asset.company_publish_state ?? (
    asset.external_origin === "official"
      ? "read_only_official"
      : asset.external_origin === "user_shared"
        ? "read_only_other"
        : "publish"
  );
  const canPublish = publishState === "publish" || publishState === "update";
  const isOtherUserAsset = publishState === "read_only_other" && asset.external_origin === "user_shared";

  return (
    <div className="group relative overflow-hidden rounded-[10px] border border-hairline-soft bg-bg-grad-a/55 transition-[transform,border-color] motion-safe:hover:-translate-y-0.5 hover:border-hairline">
      <div className="relative">
        <AssetThumb
          imageUrl={imageUrl}
          alt={asset.name}
          fallback={<Icon className="h-10 w-10 text-text-4" />}
          variant="display"
        />
        <span className="pointer-events-none absolute right-2 top-2 rounded border border-hairline bg-bg-grad-b/70 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.14em] text-text-3 backdrop-blur-sm">
          {t(`type.${asset.type}`)}
        </span>
      </div>
      <div className="p-3">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13.5px] font-semibold text-text">{asset.name}</div>
            {asset.description && (
              <div className="mt-1 line-clamp-2 text-[12px] leading-[1.55] text-text-3">
                {asset.description}
              </div>
            )}
            {formattedDate ? (
              <div className="mt-2 flex items-center gap-2 font-mono text-[10.5px] text-text-4">
                <span className="tabular-nums">{t("meta_updated_at", { date: formattedDate })}</span>
              </div>
            ) : null}
            {isOtherUserAsset ? (
              <div className="mt-1 truncate text-[10.5px] text-text-4" title={t("shared_by_read_only", {
                name: asset.external_owner_name || t("shared_by_unknown_user"),
              })}>
                {t("shared_by_read_only", {
                  name: asset.external_owner_name || t("shared_by_unknown_user"),
                })}
              </div>
            ) : null}
          </div>
          <div className="flex flex-col gap-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
            {onShare && canPublish && (
              <button
                type="button"
                onClick={() => onShare(asset)}
                disabled={sharing}
                aria-label={t(publishState === "update" ? "share_asset_update" : "share_asset")}
                className="rounded-[5px] p-1 text-text-4 transition-colors hover:text-accent-2 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
              >
                <CloudUpload className={`h-3.5 w-3.5 ${sharing ? "animate-pulse" : ""}`} />
              </button>
            )}
            <button
              type="button"
              onClick={() => onEdit(asset)}
              aria-label={t("edit")}
              className="rounded-[5px] p-1 text-text-4 transition-colors hover:text-text focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <Edit2 className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() => onDelete(asset)}
              aria-label={t("delete")}
              className="rounded-[5px] p-1 text-text-4 transition-colors hover:text-warm-bright focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-warm-ring"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
