import { useEffect, useId, useRef, useState, type DragEvent } from "react";
import { FileKey2, Loader2, Upload, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { API, type ConfigImportStatus } from "@/api";
import { GlassModal } from "@/components/ui/GlassModal";
import { useAuthStore } from "@/stores/auth-store";
import { useConfigStatusStore } from "@/stores/config-status-store";
import { errMsg } from "@/utils/async";

const ACCEPTED_SUFFIXES = [".env", ".release"];

function acceptedFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return ACCEPTED_SUFFIXES.some((suffix) => name.endsWith(suffix));
}

export function ConfigImportGate() {
  const { t } = useTranslation("dashboard");
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const titleId = useId();
  const descriptionId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<ConfigImportStatus | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuthenticated) return;
    const controller = new AbortController();
    void API.getConfigImportStatus({ signal: controller.signal })
      .then(setStatus)
      .catch((reason) => {
        if (!controller.signal.aborted) setError(errMsg(reason));
      });
    return () => controller.abort();
  }, [isAuthenticated]);

  const importFile = async (file: File) => {
    if (!acceptedFile(file)) {
      setError(t("config_import_file_type_error"));
      return;
    }
    setImporting(true);
    setError(null);
    try {
      const next = await API.importConfigFile(file);
      setStatus(next);
      if (next.ready) {
        await useConfigStatusStore.getState().refresh();
      } else {
        setError(t("config_import_incomplete"));
      }
    } catch (reason) {
      setError(errMsg(reason));
    } finally {
      setImporting(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const handleDrop = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) void importFile(file);
  };

  const open = Boolean(isAuthenticated && status?.enabled && !status.ready && !dismissed);

  return (
    <GlassModal
      open={open}
      onClose={() => setDismissed(true)}
      labelledBy={titleId}
      describedBy={descriptionId}
      widthClassName="w-full max-w-lg"
      closeOnBackdrop={!importing}
      closeOnEscape={!importing}
    >
      <div className="px-6 pb-6 pt-5">
        <div className="flex items-start gap-3">
          <span
            aria-hidden
            className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-accent/25 bg-accent/10 text-accent"
          >
            <FileKey2 className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="display-serif text-[18px] font-semibold text-text">
              {t("config_import_title")}
            </h2>
            <p id={descriptionId} className="mt-1 text-[12.5px] leading-relaxed text-text-3">
              {t("config_import_description")}
            </p>
          </div>
          <button
            type="button"
            aria-label={t("config_import_later")}
            onClick={() => setDismissed(true)}
            disabled={importing}
            className="grid h-8 w-8 place-items-center rounded-lg text-text-4 transition hover:bg-white/5 hover:text-text"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragEnter={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          disabled={importing}
          className={`mt-5 flex w-full flex-col items-center justify-center rounded-xl border border-dashed px-5 py-9 text-center transition ${
            dragging
              ? "border-accent bg-accent/10 text-accent"
              : "border-hairline bg-black/10 text-text-3 hover:border-accent/50 hover:bg-white/[0.03]"
          }`}
        >
          {importing ? (
            <Loader2 aria-hidden className="h-7 w-7 motion-safe:animate-spin" />
          ) : (
            <Upload aria-hidden className="h-7 w-7" />
          )}
          <span className="mt-3 text-[13px] font-medium text-text">
            {importing ? t("config_import_importing") : t("config_import_drop")}
          </span>
          <span className="mt-1 text-[11.5px] text-text-4">{t("config_import_hint")}</span>
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".env,.release,text/plain"
          className="hidden"
          aria-label={t("config_import_choose_file")}
          onChange={(event) => {
            const file = event.currentTarget.files?.[0];
            if (file) void importFile(file);
          }}
        />

        {error && (
          <p
            role="alert"
            className="mt-3 rounded-lg border border-warm/25 bg-warm/10 px-3 py-2 text-[12px] text-warm-bright"
          >
            {error}
          </p>
        )}
        {status?.issues.length ? (
          <p className="mt-3 text-[11.5px] text-text-4">
            {t("config_import_missing", {
              items: status.issues.map((issue) => t(`config_import_issue_${issue}`)).join("、"),
            })}
          </p>
        ) : null}
      </div>
    </GlassModal>
  );
}
