import { useRef, useState } from "react";
import { FileUp, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { errMsg } from "@/utils/async";
import {
  SOURCE_FILE_ACCEPT,
  SOURCE_FILE_FORMATS_LABEL,
  isSupportedSourceFile,
} from "@/utils/source-files";

interface CourseEpisodeUploadDialogProps {
  projectName: string;
  open: boolean;
  onClose: () => void;
  onUploaded: (episode: number) => void | Promise<void>;
}

export function CourseEpisodeUploadDialog({
  projectName,
  open,
  onClose,
  onUploaded,
}: CourseEpisodeUploadDialogProps) {
  const { t } = useTranslation(["dashboard", "common"]);
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);

  if (!open) return null;

  const upload = async (file: File) => {
    if (!isSupportedSourceFile(file.name)) {
      useAppStore.getState().pushToast(
        t("dashboard:source_unsupported_extension", { filename: file.name }),
        "error",
      );
      return;
    }
    setUploading(true);
    try {
      const result = await API.addCourseEpisode(projectName, file);
      await onUploaded(result.episode.episode);
      onClose();
      useAppStore.getState().pushToast(
        t("dashboard:course_episode_added", { episode: result.episode.episode }),
        "success",
      );
    } catch (error) {
      useAppStore.getState().pushToast(
        t("dashboard:course_episode_add_failed", { message: errMsg(error) }),
        "error",
      );
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[80] grid place-items-center bg-black/60 p-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("dashboard:add_course_episode")}
        className="w-full max-w-md rounded-2xl border border-hairline bg-bg-grad-a p-5 shadow-2xl"
      >
        <div className="mb-4 flex items-center gap-2">
          <FileUp className="h-4 w-4 text-accent-2" />
          <h2 className="flex-1 text-sm font-semibold text-text">
            {t("dashboard:add_course_episode")}
          </h2>
          <button type="button" onClick={onClose} disabled={uploading} className="focus-ring rounded p-1 text-text-3">
            <X className="h-4 w-4" />
          </button>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept={SOURCE_FILE_ACCEPT}
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void upload(file);
            event.currentTarget.value = "";
          }}
        />
        <button
          type="button"
          disabled={uploading}
          onClick={() => inputRef.current?.click()}
          onDragOver={(event) => {
            event.preventDefault();
            if (!uploading) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            const file = event.dataTransfer.files?.[0];
            if (file && !uploading) void upload(file);
          }}
          className={`focus-ring grid min-h-48 w-full place-items-center rounded-xl border border-dashed px-6 py-8 text-center transition-colors ${
            dragging ? "border-accent bg-accent-dim" : "border-hairline bg-bg-grad-b/40"
          }`}
        >
          <span>
            {uploading ? (
              <Loader2 className="mx-auto mb-3 h-7 w-7 animate-spin text-accent-2" />
            ) : (
              <FileUp className="mx-auto mb-3 h-7 w-7 text-accent-2" />
            )}
            <span className="block text-sm font-medium text-text-2">
              {uploading ? t("common:loading") : t("dashboard:course_episode_drop_hint")}
            </span>
            <span className="mt-2 block font-mono text-[10px] text-text-4">
              {SOURCE_FILE_FORMATS_LABEL}
            </span>
          </span>
        </button>
      </div>
    </div>
  );
}
