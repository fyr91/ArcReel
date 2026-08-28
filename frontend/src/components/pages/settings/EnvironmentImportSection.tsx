import { useRef, useState, type DragEvent } from "react";
import { FileKey2, Loader2, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";

import { API, type ConfigImportPreview } from "@/api";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useAppStore } from "@/stores/app-store";
import { useConfigStatusStore } from "@/stores/config-status-store";
import { errMsg } from "@/utils/async";

const ACCEPTED_SUFFIXES = [".env", ".release"];

function acceptedFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return ACCEPTED_SUFFIXES.some((suffix) => name.endsWith(suffix));
}

export function EnvironmentImportSection() {
  const { t } = useTranslation("dashboard");
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [checking, setChecking] = useState(false);
  const [importing, setImporting] = useState(false);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ConfigImportPreview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const inspectFile = async (file: File) => {
    if (!acceptedFile(file)) {
      setError(t("config_import_file_type_error"));
      return;
    }
    setChecking(true);
    setError(null);
    try {
      const next = await API.previewConfigFile(file);
      setPendingFile(file);
      setPreview(next);
    } catch (reason) {
      setError(errMsg(reason));
    } finally {
      setChecking(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const handleDrop = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) void inspectFile(file);
  };

  const closePreview = () => {
    if (importing) return;
    setPendingFile(null);
    setPreview(null);
  };

  const applyEnvironment = async () => {
    if (!pendingFile) return;
    setImporting(true);
    setError(null);
    try {
      await API.importConfigFile(pendingFile, { replaceExisting: true, updateProjects: true });
      await useConfigStatusStore.getState().refresh();
      useAppStore.getState().pushToast(t("environment_import_success"), "success");
      setPendingFile(null);
      setPreview(null);
    } catch (reason) {
      setError(errMsg(reason));
    } finally {
      setImporting(false);
    }
  };

  return (
    <>
      <section className="overflow-hidden rounded-[12px] border border-hairline bg-bg-grad-a/45">
        <header className="border-b border-hairline-soft px-5 pb-3 pt-4">
          <div className="font-mono text-[10px] font-bold uppercase tracking-[0.16em] text-accent-2">
            {t("environment_import_kicker")}
          </div>
          <h2 className="mt-1 text-[15px] font-semibold tracking-tight text-text">
            {t("environment_import_title")}
          </h2>
          <p className="mt-1 text-[12px] leading-[1.55] text-text-3">
            {t("environment_import_description")}
          </p>
        </header>
        <div className="p-5">
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
            disabled={checking || importing}
            className={`flex w-full flex-col items-center justify-center rounded-xl border border-dashed px-5 py-10 text-center transition ${
              dragging
                ? "border-accent bg-accent/10 text-accent"
                : "border-hairline bg-black/10 text-text-3 hover:border-accent/50 hover:bg-white/[0.03]"
            }`}
          >
            {checking ? (
              <Loader2 aria-hidden className="h-7 w-7 motion-safe:animate-spin" />
            ) : (
              <Upload aria-hidden className="h-7 w-7" />
            )}
            <span className="mt-3 text-[13px] font-medium text-text">
              {checking ? t("environment_import_checking") : t("config_import_drop")}
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
              if (file) void inspectFile(file);
            }}
          />
          <div className="mt-4 flex items-start gap-2 rounded-lg border border-warm/20 bg-warm/5 px-3 py-2.5 text-[11.5px] leading-relaxed text-text-3">
            <FileKey2 aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warm" />
            <span>{t("environment_import_warning")}</span>
          </div>
          {error && (
            <p role="alert" className="mt-3 rounded-lg border border-warm/25 bg-warm/10 px-3 py-2 text-[12px] text-warm-bright">
              {error}
            </p>
          )}
        </div>
      </section>

      <ConfirmDialog
        open={Boolean(preview && pendingFile)}
        title={t("environment_import_confirm_title")}
        description={preview ? (
          <div className="space-y-2">
            <p>{t("environment_import_confirm_description")}</p>
            <ul className="list-disc space-y-1 pl-4">
              <li>{t("environment_import_preview_providers", { builtin: preview.builtin_providers, custom: preview.custom_providers })}</li>
              <li>{t("environment_import_preview_settings", { count: preview.system_settings })}</li>
              <li>{t("environment_import_preview_projects", { count: preview.projects_to_update })}</li>
            </ul>
          </div>
        ) : undefined}
        confirmLabel={t("environment_import_confirm")}
        loadingLabel={t("config_import_importing")}
        tone="danger"
        loading={importing}
        onConfirm={applyEnvironment}
        onCancel={closePreview}
      />
    </>
  );
}
