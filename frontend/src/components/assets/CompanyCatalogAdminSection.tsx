import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Database,
  Landmark,
  Loader2,
  Package,
  Search,
  Trash2,
  User,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useAppStore } from "@/stores/app-store";
import type { CompanyCatalogAsset, CompanyCatalogAssetPage } from "@/types";
import type { AssetType } from "@/types/asset";
import { errMsg } from "@/utils/async";
import { AssetThumb } from "./AssetThumb";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { INPUT_CLS } from "@/components/ui/darkroom-tokens";

const PAGE_SIZE = 24;
const TYPE_ICONS = { character: User, scene: Landmark, prop: Package };

type Origin = "official" | "user_shared";

function CompanyCatalogPreview({ asset }: { asset: CompanyCatalogAsset }) {
  const [url, setUrl] = useState<string | null>(null);
  const Icon = TYPE_ICONS[asset.asset_type];
  const hasImage = asset.files.some((file) => file.media_type === "image");

  useEffect(() => {
    if (!hasImage) return;
    let active = true;
    let objectUrl: string | null = null;
    void API.getCompanyCatalogAssetPreview(asset.id)
      .then((blob) => {
        if (!active || !blob.size) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => undefined);
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [asset.id, hasImage]);

  return (
    <AssetThumb
      imageUrl={url}
      alt={asset.name}
      fallback={<Icon className="h-10 w-10 text-text-4" />}
      variant="display"
    />
  );
}

export function CompanyCatalogAdminSection() {
  const { t } = useTranslation("assets");
  const [page, setPage] = useState<CompanyCatalogAssetPage | null>(null);
  const [query, setQuery] = useState("");
  const [assetType, setAssetType] = useState<AssetType | "">("");
  const [origin, setOrigin] = useState<Origin | "">("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<CompanyCatalogAsset | null>(null);
  const [deleting, setDeleting] = useState(false);
  const debouncedQuery = useDebouncedValue(query, 250);
  const requestSequence = useRef(0);

  const fetchPage = useCallback(() => API.listCompanyCatalogAssets({
    assetType: assetType || undefined,
    origin: origin || undefined,
    q: debouncedQuery || undefined,
    limit: PAGE_SIZE,
    offset,
  }), [assetType, debouncedQuery, offset, origin]);

  const reload = useCallback(async () => {
    const sequence = ++requestSequence.current;
    setLoading(true);
    try {
      const next = await fetchPage();
      if (sequence === requestSequence.current) setPage(next);
    } catch (error) {
      if (sequence === requestSequence.current) {
        useAppStore.getState().pushToast(errMsg(error), "error");
      }
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }, [fetchPage]);

  useEffect(() => {
    const sequence = ++requestSequence.current;
    void fetchPage()
      .then((next) => {
        if (sequence === requestSequence.current) setPage(next);
      })
      .catch((error) => {
        if (sequence === requestSequence.current) {
          useAppStore.getState().pushToast(errMsg(error), "error");
        }
      })
      .finally(() => {
        if (sequence === requestSequence.current) setLoading(false);
      });
  }, [fetchPage]);

  const pageNumber = Math.floor(offset / PAGE_SIZE) + 1;
  const pageCount = Math.max(1, Math.ceil((page?.total ?? 0) / PAGE_SIZE));
  const summary = useMemo(
    () => ["character", "scene", "prop"].map((type) => ({
      type: type as AssetType,
      count: page?.totals[type as AssetType] ?? 0,
    })),
    [page?.totals],
  );

  const resetOffset = () => setOffset(0);

  const confirmDelete = async () => {
    if (!deleteTarget || deleting) return;
    const target = deleteTarget;
    setDeleting(true);
    try {
      await API.deleteCompanyCatalogAsset(target.id);
      setDeleteTarget(null);
      useAppStore.getState().pushToast(t("source_catalog_delete_success", { name: target.name }), "success");
      if (page?.items.length === 1 && offset > 0) {
        setOffset(Math.max(0, offset - PAGE_SIZE));
      } else {
        await reload();
      }
    } catch (error) {
      useAppStore.getState().pushToast(errMsg(error), "error");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <section className="mt-8 overflow-hidden rounded-xl border border-hairline-soft bg-bg-grad-a/45">
      <div className="border-b border-hairline-soft px-4 py-4 sm:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-hairline bg-bg-grad-b/60 text-accent-2">
              <Database className="h-4 w-4" />
            </span>
            <div>
              <h2 className="font-editorial text-xl">{t("source_catalog_title")}</h2>
              <p className="mt-1 max-w-2xl text-xs leading-relaxed text-text-3">
                {t("source_catalog_subtitle")}
              </p>
            </div>
          </div>
          <div className="flex gap-1.5" aria-label={t("source_catalog_counts")}>
            {summary.map(({ type, count }) => (
              <span key={type} className="rounded-full border border-hairline px-2 py-1 font-mono text-[10px] text-text-3">
                {t(`type.${type}`)} {count}
              </span>
            ))}
          </div>
        </div>

        <div className="mt-4 grid gap-2 sm:grid-cols-[minmax(220px,1fr)_160px_160px]">
          <label className="relative">
            <span className="sr-only">{t("source_catalog_search_label")}</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-4" />
            <input
              type="search"
              aria-label={t("source_catalog_search_label")}
              placeholder={t("source_catalog_search_placeholder")}
              value={query}
              onChange={(event) => {
                requestSequence.current += 1;
                setLoading(true);
                setQuery(event.target.value);
                resetOffset();
              }}
              className={`${INPUT_CLS} w-full pl-9`}
            />
          </label>
          <select
            aria-label={t("source_catalog_type_filter")}
            value={assetType}
            onChange={(event) => {
              requestSequence.current += 1;
              setLoading(true);
              setAssetType(event.target.value as AssetType | "");
              resetOffset();
            }}
            className={INPUT_CLS}
          >
            <option value="">{t("source_catalog_all_types")}</option>
            <option value="character">{t("type.character")}</option>
            <option value="scene">{t("type.scene")}</option>
            <option value="prop">{t("type.prop")}</option>
          </select>
          <select
            aria-label={t("source_catalog_origin_filter")}
            value={origin}
            onChange={(event) => {
              requestSequence.current += 1;
              setLoading(true);
              setOrigin(event.target.value as Origin | "");
              resetOffset();
            }}
            className={INPUT_CLS}
          >
            <option value="">{t("source_catalog_all_origins")}</option>
            <option value="official">{t("source_catalog_origin_official")}</option>
            <option value="user_shared">{t("source_catalog_origin_shared")}</option>
          </select>
        </div>
      </div>

      <div className="p-4 sm:p-5">
        {loading && !page ? (
          <div className="flex min-h-40 items-center justify-center text-text-4">
            <Loader2 className="h-5 w-5 motion-safe:animate-spin" aria-label={t("loading")} />
          </div>
        ) : page?.items.length ? (
          <div className={`grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 ${loading ? "opacity-60" : ""}`}>
            {page.items.map((asset) => (
              <article key={asset.id} className="group overflow-hidden rounded-[10px] border border-hairline-soft bg-bg-grad-a/70">
                <CompanyCatalogPreview asset={asset} />
                <div className="p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h3 className="truncate text-sm font-semibold">{asset.name}</h3>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5 font-mono text-[10px] text-text-4">
                        <span>{t(`type.${asset.asset_type}`)}</span>
                        <span>·</span>
                        <span>{t(`source_catalog_origin_${asset.origin === "official" ? "official" : "shared"}`)}</span>
                        <span>·</span>
                        <span>v{asset.version}</span>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setDeleteTarget(asset)}
                      aria-label={t("source_catalog_delete_asset", { name: asset.name })}
                      className="rounded-md p-1.5 text-text-4 transition-colors hover:bg-warm-tint-faint hover:text-warm-bright focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-warm-ring"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                  {asset.description ? <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-text-3">{asset.description}</p> : null}
                  <div className="mt-3 flex items-center justify-between gap-2 border-t border-hairline-soft pt-2 text-[10px] text-text-4">
                    <span className="truncate">{asset.source_name ?? asset.owner_name ?? "—"}</span>
                    <span>{t("source_catalog_file_count", { count: asset.files.length })}</span>
                  </div>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="flex min-h-40 flex-col items-center justify-center text-center">
            <Database className="h-7 w-7 text-text-4" />
            <p className="mt-3 text-sm text-text-3">{t("source_catalog_empty")}</p>
          </div>
        )}

        {page && page.total > PAGE_SIZE ? (
          <div className="mt-5 flex items-center justify-between border-t border-hairline-soft pt-4">
            <button
              type="button"
              disabled={offset === 0 || loading}
              onClick={() => {
                setLoading(true);
                setOffset(Math.max(0, offset - PAGE_SIZE));
              }}
              className="inline-flex items-center gap-1 text-xs text-text-3 hover:text-text disabled:opacity-40"
            >
              <ChevronLeft className="h-4 w-4" /> {t("source_catalog_previous")}
            </button>
            <span className="font-mono text-[10px] text-text-4">{t("source_catalog_page", { page: pageNumber, pages: pageCount })}</span>
            <button
              type="button"
              disabled={offset + PAGE_SIZE >= page.total || loading}
              onClick={() => {
                setLoading(true);
                setOffset(offset + PAGE_SIZE);
              }}
              className="inline-flex items-center gap-1 text-xs text-text-3 hover:text-text disabled:opacity-40"
            >
              {t("source_catalog_next")} <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        ) : null}
      </div>

      <ConfirmDialog
        open={deleteTarget !== null}
        title={t("source_catalog_delete_title", { name: deleteTarget?.name ?? "" })}
        description={deleteTarget ? (
          <div className="space-y-2">
            <p>{t("source_catalog_delete_description")}</p>
            <p>{t(deleteTarget.origin === "official" ? "source_catalog_delete_official_note" : "source_catalog_delete_shared_note")}</p>
          </div>
        ) : undefined}
        confirmLabel={t("source_catalog_delete_confirm")}
        loadingLabel={t("source_catalog_deleting")}
        tone="danger"
        loading={deleting}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </section>
  );
}
