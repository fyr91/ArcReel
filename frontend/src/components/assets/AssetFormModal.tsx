import { useEffect, useId, useState, useRef } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  AudioLines,
  Check,
  ChevronDown,
  Image as ImageIcon,
  ImagePlus,
  Landmark,
  Package,
  Pause,
  Play,
  Trash2,
  Upload,
  User,
} from "lucide-react";
import { API } from "@/api";
import type { Asset, AssetResource, AssetType } from "@/types/asset";
import { GlassModal } from "@/components/ui/GlassModal";
import { ModalCloseButton } from "@/components/ui/ModalCloseButton";
import { PrimaryButton } from "@/components/ui/PrimaryButton";
import { SecondaryButton } from "@/components/ui/SecondaryButton";
import { sanitizeImageSrc } from "@/utils/safe-url";
import { WARM_TONE } from "@/utils/severity-tone";

type Mode = "create" | "edit" | "import";

interface Props {
  type: AssetType;
  mode: Mode;
  initialData?: Partial<Asset>;
  previewImageUrl?: string;
  conflictWith?: Asset;
  manageResourceGroups?: boolean;
  onClose: () => void;
  onSubmit: (payload: {
    name: string;
    description: string;
    voice_style: string;
    voice_id: string;
    image?: File | null;
    images?: File[];
    audios?: File[];
    remove_resource_ids?: string[];
    overwrite?: boolean;
    primary_image_resource_id?: string;
    primary_audio_resource_id?: string;
    primary_image_upload_index?: number;
    primary_audio_upload_index?: number;
  }) => Promise<void>;
}

interface PendingMedia {
  id: string;
  file: File;
  previewUrl: string;
}

const TYPE_ICON: Record<AssetType, React.ComponentType<{ className?: string }>> = {
  character: User,
  scene: Landmark,
  prop: Package,
};

export function AssetFormModal({
  type,
  mode,
  initialData,
  previewImageUrl,
  conflictWith,
  manageResourceGroups = false,
  onClose,
  onSubmit,
}: Props) {
  const { t } = useTranslation("assets");
  const [name, setName] = useState(initialData?.name ?? "");
  const [description, setDescription] = useState(initialData?.description ?? "");
  const [voiceStyle, setVoiceStyle] = useState(initialData?.voice_style ?? "");
  const [voiceId, setVoiceId] = useState(initialData?.voice_id ?? "");
  const [image, setImage] = useState<File | null>(null);
  const [pendingImages, setPendingImages] = useState<PendingMedia[]>([]);
  const [pendingAudios, setPendingAudios] = useState<PendingMedia[]>([]);
  const [removedResourceIds, setRemovedResourceIds] = useState<Set<string>>(() => new Set());
  const objectUrlsRef = useRef<Set<string>>(new Set());
  const [localPreview, setLocalPreview] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const resources = initialData?.resources ?? [];
  const imageResources = resources.filter(
    (resource) => resource.media_type === "image" && !removedResourceIds.has(resource.id),
  );
  const audioResources = resources.filter(
    (resource) => resource.media_type === "audio" && !removedResourceIds.has(resource.id),
  );
  const [primaryImageResourceId, setPrimaryImageResourceId] = useState(
    imageResources.find((resource) => resource.is_primary)?.id ?? imageResources[0]?.id ?? "",
  );
  const [primaryAudioResourceId, setPrimaryAudioResourceId] = useState(
    audioResources.find((resource) => resource.is_primary)?.id ?? audioResources[0]?.id ?? "",
  );
  const [primaryPendingImageId, setPrimaryPendingImageId] = useState<string | null>(null);
  const [primaryPendingAudioId, setPrimaryPendingAudioId] = useState<string | null>(null);
  const selectedImageResource = imageResources.find((resource) => resource.id === primaryImageResourceId);
  const fileRef = useRef<HTMLInputElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const titleId = useId();

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!image) {
      // image 变更时同步重置本地预览（动作驱动重置）
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLocalPreview(null);
      return;
    }
    const url = URL.createObjectURL(image);
    setLocalPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [image]);

  useEffect(() => () => {
    for (const url of objectUrlsRef.current) URL.revokeObjectURL(url);
    objectUrlsRef.current.clear();
  }, []);

  const addPending = (files: FileList | null, mediaType: "image" | "audio") => {
    if (!files?.length) return;
    const additions = Array.from(files).map((file) => {
      const previewUrl = URL.createObjectURL(file);
      objectUrlsRef.current.add(previewUrl);
      return { id: crypto.randomUUID(), file, previewUrl };
    });
    if (mediaType === "image") {
      setPendingImages((current) => [...current, ...additions]);
      if (!primaryImageResourceId && !primaryPendingImageId) {
        setPrimaryPendingImageId(additions[0].id);
      }
    } else {
      setPendingAudios((current) => [...current, ...additions]);
      if (!primaryAudioResourceId && !primaryPendingAudioId) {
        setPrimaryPendingAudioId(additions[0].id);
      }
    }
  };

  const removePending = (id: string, mediaType: "image" | "audio") => {
    const current = mediaType === "image" ? pendingImages : pendingAudios;
    const target = current.find((item) => item.id === id);
    if (target) {
      URL.revokeObjectURL(target.previewUrl);
      objectUrlsRef.current.delete(target.previewUrl);
    }
    const next = current.filter((item) => item.id !== id);
    if (mediaType === "image") {
      setPendingImages(next);
      if (primaryPendingImageId === id) {
        setPrimaryPendingImageId(next[0]?.id ?? null);
        if (!next.length) setPrimaryImageResourceId(imageResources[0]?.id ?? "");
      }
    } else {
      setPendingAudios(next);
      if (primaryPendingAudioId === id) {
        setPrimaryPendingAudioId(next[0]?.id ?? null);
        if (!next.length) setPrimaryAudioResourceId(audioResources[0]?.id ?? "");
      }
    }
  };

  const removeExisting = (resource: AssetResource) => {
    if (resource.origin !== "local") return;
    setRemovedResourceIds((current) => new Set(current).add(resource.id));
    if (resource.media_type === "image" && primaryImageResourceId === resource.id) {
      const fallback = imageResources.find((item) => item.id !== resource.id);
      setPrimaryImageResourceId(fallback?.id ?? "");
      if (!fallback && pendingImages.length) setPrimaryPendingImageId(pendingImages[0].id);
    }
    if (resource.media_type === "audio" && primaryAudioResourceId === resource.id) {
      const fallback = audioResources.find((item) => item.id !== resource.id);
      setPrimaryAudioResourceId(fallback?.id ?? "");
      if (!fallback && pendingAudios.length) setPrimaryPendingAudioId(pendingAudios[0].id);
    }
  };

  const selectedPendingImage = pendingImages.find((item) => item.id === primaryPendingImageId);
  const selectedResourcePreview = selectedImageResource
    ? API.getGlobalAssetUrl(selectedImageResource.path, initialData?.updated_at)
    : null;
  const displayedPreview = sanitizeImageSrc(
    selectedPendingImage?.previewUrl ?? localPreview ?? selectedResourcePreview ?? previewImageUrl,
  );
  const TypeIcon = TYPE_ICON[type];

  const isCharacter = type === "character";
  const typeLabel = t(`type.${type}`);
  const title = mode === "create" ? t("create_title", { type: typeLabel })
    : mode === "edit" ? t("edit_title", { type: typeLabel, name: initialData?.name })
    : t("import_title", { name: initialData?.name });

  const primaryLabel = mode === "create" ? t("create") : mode === "edit" ? t("save") : t("confirm_import");

  const submit = async (overwrite = false) => {
    setSubmitting(true);
    try {
      await onSubmit({
        name: name.trim(),
        description,
        voice_style: voiceStyle,
        voice_id: voiceId.trim(),
        image: manageResourceGroups ? null : image,
        images: manageResourceGroups ? pendingImages.map((item) => item.file) : undefined,
        audios: manageResourceGroups ? pendingAudios.map((item) => item.file) : undefined,
        remove_resource_ids: manageResourceGroups ? [...removedResourceIds] : undefined,
        overwrite,
        primary_image_resource_id: primaryPendingImageId ? undefined : primaryImageResourceId || undefined,
        primary_audio_resource_id: primaryPendingAudioId ? undefined : primaryAudioResourceId || undefined,
        primary_image_upload_index: primaryPendingImageId
          ? pendingImages.findIndex((item) => item.id === primaryPendingImageId)
          : undefined,
        primary_audio_upload_index: primaryPendingAudioId
          ? pendingAudios.findIndex((item) => item.id === primaryPendingAudioId)
          : undefined,
      });
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <GlassModal
      open
      onClose={onClose}
      labelledBy={titleId}
      widthClassName={manageResourceGroups ? "w-[760px] max-w-[96vw]" : "w-[580px] max-w-[96vw]"}
    >
      {/* Header */}
        <div
          className="flex items-start gap-3 px-6 py-5"
          style={{ borderBottom: "1px solid var(--color-hairline-soft)" }}
        >
          <span
            aria-hidden
            className="grid h-9 w-9 shrink-0 place-items-center rounded-lg"
            style={{
              background:
                "linear-gradient(135deg, var(--color-accent-dim), oklch(0.76 0.09 160 / 0.05))",
              border: "1px solid var(--color-accent-soft)",
              color: "var(--color-accent-2)",
              boxShadow: "0 8px 18px -8px var(--color-accent-glow)",
            }}
          >
            <TypeIcon className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <h3
              id={titleId}
              className="display-serif truncate text-[15px] font-semibold tracking-tight"
              style={{ color: "var(--color-text)" }}
            >
              {title}
            </h3>
            <p
              className="num mt-0.5 text-[10px] uppercase"
              style={{
                color: "var(--color-text-4)",
                letterSpacing: "1.0px",
              }}
            >
              {mode === "import" ? t("library_subtitle") : typeLabel}
            </p>
          </div>
          <ModalCloseButton onClick={onClose} />
        </div>

        {/* Conflict warning */}
        {conflictWith && (
          <div
            className="flex items-start gap-2 px-6 py-3 text-[12px]"
            style={{
              borderBottom: `1px solid ${WARM_TONE.ring}`,
              background: WARM_TONE.soft,
              color: WARM_TONE.color,
            }}
          >
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>{t("conflict_warning", { name: conflictWith.name })}</span>
          </div>
        )}

        {/* Body */}
        <div className="grid max-h-[68vh] grid-cols-[220px_1fr] gap-5 overflow-y-auto p-6">
          {/* Image uploader */}
          <div>
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="focus-ring group relative aspect-video w-full overflow-hidden rounded-xl transition-colors"
              style={{
                background: "oklch(0.16 0.010 265 / 0.6)",
                border: "1px dashed var(--color-hairline)",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = "var(--color-accent-soft)";
                e.currentTarget.style.borderStyle = "dashed";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = "var(--color-hairline)";
              }}
            >
              {displayedPreview ? (
                <>
                  <img
                    src={displayedPreview}
                    alt=""
                    className="absolute inset-0 h-full w-full object-contain"
                  />
                  <div
                    className="absolute inset-0 flex items-center justify-center gap-2 text-[13px] opacity-0 transition-opacity group-hover:opacity-100"
                    style={{
                      background: "oklch(0 0 0 / 0.6)",
                      color: "var(--color-text)",
                    }}
                  >
                    <ImagePlus className="h-4 w-4" />
                    {manageResourceGroups ? t("add_images") : t("replace_image")}
                  </div>
                </>
              ) : (
                <div
                  className="flex h-full w-full flex-col items-center justify-center gap-2 px-4 text-center transition-colors"
                  style={{ color: "var(--color-text-4)" }}
                >
                  <span
                    aria-hidden
                    className="grid h-10 w-10 place-items-center rounded-full"
                    style={{
                      background:
                        "linear-gradient(135deg, var(--color-accent-dim), oklch(0.76 0.09 160 / 0.05))",
                      border: "1px solid var(--color-accent-soft)",
                      color: "var(--color-accent-2)",
                    }}
                  >
                    <ImagePlus className="h-4 w-4" />
                  </span>
                  <span
                    className="text-[12px]"
                    style={{ color: "var(--color-text-3)" }}
                  >
                    {t("upload_image_hint")}
                  </span>
                  <span
                    className="text-[10px]"
                    style={{ color: "var(--color-text-4)" }}
                  >
                    {t("upload_image_optional")}
                  </span>
                </div>
              )}
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".png,.jpg,.jpeg,.webp"
              multiple={manageResourceGroups}
              className="hidden"
              onChange={(event) => {
                if (manageResourceGroups) addPending(event.target.files, "image");
                else setImage(event.target.files?.[0] ?? null);
                event.currentTarget.value = "";
              }}
            />
            {manageResourceGroups && (
              <p className="mt-2 text-[10px] leading-relaxed text-text-4">
                {t("resource_group_limit_hint")}
              </p>
            )}
          </div>

          {/* Form fields */}
          <div className="flex flex-col gap-4">
            <FieldLabel
              label={
                <>
                  {t("field.name")}{" "}
                  <span style={{ color: "var(--color-accent-2)" }}>*</span>
                </>
              }
            >
              <input
                ref={nameRef}
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="focus-ring rounded-lg px-3 py-2 text-[13px] outline-none"
                style={{
                  background: "oklch(0.16 0.010 265 / 0.6)",
                  border: "1px solid var(--color-hairline)",
                  color: "var(--color-text)",
                }}
              />
            </FieldLabel>

            <FieldLabel label={t("field.description")}>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={4}
                className="focus-ring resize-none rounded-lg px-3 py-2 text-[13px] leading-[1.55] outline-none"
                style={{
                  background: "oklch(0.16 0.010 265 / 0.6)",
                  border: "1px solid var(--color-hairline)",
                  color: "var(--color-text)",
                }}
              />
            </FieldLabel>

            {isCharacter && (
              <FieldLabel label={t("field.voice_style")}>
                <input
                  value={voiceStyle}
                  onChange={(e) => setVoiceStyle(e.target.value)}
                  className="focus-ring rounded-lg px-3 py-2 text-[13px] outline-none"
                  style={{
                    background: "oklch(0.16 0.010 265 / 0.6)",
                    border: "1px solid var(--color-hairline)",
                    color: "var(--color-text)",
                  }}
                />
              </FieldLabel>
            )}

            {isCharacter && (manageResourceGroups || initialData?.voice_id) && (
              <FieldLabel label={t("field.voice_id")}>
                <input
                  value={voiceId}
                  onChange={(event) => setVoiceId(event.target.value)}
                  readOnly={!manageResourceGroups}
                  placeholder={manageResourceGroups ? t("voice_id_placeholder") : undefined}
                  className="focus-ring rounded-lg px-3 py-2 font-mono text-[11px] outline-none read-only:cursor-default"
                  style={{
                    background: "oklch(0.16 0.010 265 / 0.45)",
                    border: "1px solid var(--color-hairline-soft)",
                    color: "var(--color-text-3)",
                  }}
                />
              </FieldLabel>
            )}

            {manageResourceGroups && (
              <FieldGroup label={t("field.image_group", {
                count: imageResources.length + pendingImages.length,
              })}>
                {imageResources.length > 0 && (
                <ImageResourcePicker
                  resources={imageResources}
                  value={primaryImageResourceId}
                  fingerprint={initialData?.updated_at}
                  onChange={(resourceId) => {
                    setPrimaryImageResourceId(resourceId);
                    setPrimaryPendingImageId(null);
                  }}
                />
                )}
                <ResourceRemovalList
                  resources={imageResources}
                  mediaType="image"
                  onRemove={removeExisting}
                />
                <PendingMediaList
                  items={pendingImages}
                  mediaType="image"
                  primaryId={primaryPendingImageId}
                  onPrimary={(id) => {
                    setPrimaryPendingImageId(id);
                    setPrimaryImageResourceId("");
                  }}
                  onRemove={(id) => removePending(id, "image")}
                />
              </FieldGroup>
            )}

            {isCharacter && manageResourceGroups && (
              <FieldGroup label={t("field.audio_group", {
                count: audioResources.length + pendingAudios.length,
              })}>
                {audioResources.length > 0 && (
                <AudioResourcePicker
                  resources={audioResources}
                  value={primaryAudioResourceId}
                  fingerprint={initialData?.updated_at}
                  onChange={(resourceId) => {
                    setPrimaryAudioResourceId(resourceId);
                    setPrimaryPendingAudioId(null);
                  }}
                />
                )}
                <ResourceRemovalList
                  resources={audioResources}
                  mediaType="audio"
                  onRemove={removeExisting}
                />
                <PendingMediaList
                  items={pendingAudios}
                  mediaType="audio"
                  primaryId={primaryPendingAudioId}
                  onPrimary={(id) => {
                    setPrimaryPendingAudioId(id);
                    setPrimaryAudioResourceId("");
                  }}
                  onRemove={(id) => removePending(id, "audio")}
                />
                <label
                  className="focus-within:focus-ring flex cursor-pointer items-center justify-center gap-2 rounded-lg px-3 py-2 text-[12px] text-text-3 outline-none transition-colors hover:bg-white/5"
                  style={{ border: "1px dashed var(--color-hairline)" }}
                >
                  <Upload aria-hidden className="h-4 w-4" />
                  {t("add_audios")}
                  <input
                    type="file"
                    accept=".wav,.mp3,.m4a,.aac,.ogg,.flac,audio/*"
                    multiple
                    className="sr-only"
                    onChange={(event) => {
                      addPending(event.target.files, "audio");
                      event.currentTarget.value = "";
                    }}
                  />
                </label>
              </FieldGroup>
            )}
          </div>
        </div>

        {/* Footer */}
        <div
          className="flex items-center gap-2 px-6 py-4"
          style={{
            borderTop: "1px solid var(--color-hairline-soft)",
            background: "oklch(0.17 0.010 250 / 0.5)",
          }}
        >
          <SecondaryButton size="sm" onClick={onClose}>
            {t("cancel")}
          </SecondaryButton>
          {mode === "import" && conflictWith && (
            <PrimaryButton
              size="sm"
              tone="warm"
              onClick={() => void submit(true)}
              disabled={submitting}
            >
              {t("overwrite_existing")}
            </PrimaryButton>
          )}
          <PrimaryButton
            size="sm"
            className="ml-auto"
            onClick={() => void submit(false)}
            disabled={submitting || !name.trim()}
          >
            {primaryLabel}
          </PrimaryButton>
        </div>
    </GlassModal>
  );
}

function ImageResourcePicker({
  resources,
  value,
  fingerprint,
  onChange,
}: {
  resources: AssetResource[];
  value: string;
  fingerprint?: string | null;
  onChange: (resourceId: string) => void;
}) {
  const { t } = useTranslation("assets");
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();
  const selectedIndex = Math.max(0, resources.findIndex((resource) => resource.id === value));
  const selected = resources[selectedIndex];

  useEffect(() => {
    if (!open) return;
    const closeOnOutside = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const labelFor = (resource: AssetResource, index: number) => {
    const knownLabels: Record<string, string> = {
      avatarUrl: t("resource_image_avatar"),
      fullBodyImageUrl: t("resource_image_full_body"),
      halfBodyImageUrl: t("resource_image_half_body"),
      chestImageUrl: t("resource_image_chest"),
    };
    return knownLabels[resource.key] ?? t("resource_image_option", { index: index + 1 });
  };

  const thumbnail = (resource: AssetResource, label: string) => {
    const src = sanitizeImageSrc(API.getGlobalAssetUrl(resource.path, fingerprint));
    return (
      <span
        className="relative grid h-10 w-14 shrink-0 place-items-center overflow-hidden rounded-md"
        style={{ background: "oklch(0.13 0.008 265)", border: "1px solid var(--color-hairline-soft)" }}
      >
        <ImageIcon aria-hidden className="h-4 w-4 text-text-4" />
        {src && (
          <img
            src={src}
            alt={label}
            className="absolute inset-0 h-full w-full object-cover"
            onError={(event) => { event.currentTarget.style.display = "none"; }}
          />
        )}
      </span>
    );
  };

  if (!selected) return null;
  const selectedLabel = labelFor(selected, selectedIndex);

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        onClick={() => setOpen((current) => !current)}
        className="focus-ring flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left outline-none"
        style={{
          background: "oklch(0.16 0.010 265 / 0.6)",
          border: "1px solid var(--color-hairline)",
          color: "var(--color-text)",
        }}
      >
        {thumbnail(selected, selectedLabel)}
        <span className="min-w-0 flex-1 truncate text-[12px]">{selectedLabel}</span>
        <ChevronDown aria-hidden className={`h-4 w-4 shrink-0 text-text-4 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div
          id={listboxId}
          role="listbox"
          aria-label={t("field.primary_image")}
          className="absolute inset-x-0 top-full z-20 mt-1 max-h-64 overflow-y-auto rounded-lg border p-1 shadow-2xl"
          style={{ background: "oklch(0.17 0.010 265)", borderColor: "var(--color-hairline)" }}
        >
          {resources.map((resource, index) => {
            const label = labelFor(resource, index);
            const selectedOption = resource.id === value;
            return (
              <button
                key={resource.id}
                type="button"
                role="option"
                aria-selected={selectedOption}
                onClick={() => {
                  onChange(resource.id);
                  setOpen(false);
                }}
                className="focus-ring flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left outline-none transition-colors hover:bg-white/5"
              >
                {thumbnail(resource, label)}
                <span className="min-w-0 flex-1 truncate text-[12px] text-text-2">{label}</span>
                {selectedOption && <Check aria-hidden className="h-4 w-4 shrink-0 text-accent" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function AudioResourcePicker({
  resources,
  value,
  fingerprint,
  onChange,
}: {
  resources: AssetResource[];
  value: string;
  fingerprint?: string | null;
  onChange: (resourceId: string) => void;
}) {
  const { t } = useTranslation("assets");
  const [open, setOpen] = useState(false);
  const [playingResourceId, setPlayingResourceId] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const panelId = useId();
  const selectedIndex = Math.max(0, resources.findIndex((resource) => resource.id === value));
  const selected = resources[selectedIndex];

  useEffect(() => {
    if (!open) return;
    const closeOnOutside = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  useEffect(() => () => audioRef.current?.pause(), []);

  const labelFor = (_resource: AssetResource, index: number) => (
    t("resource_audio_option", { index: index + 1 })
  );

  const urlFor = (resource: AssetResource) => (
    API.getGlobalAssetUrl(resource.path, fingerprint)
  );

  const togglePreview = (resource: AssetResource) => {
    const audio = audioRef.current;
    const url = urlFor(resource);
    if (!audio || !url) return;

    if (playingResourceId === resource.id) {
      audio.pause();
      setPlayingResourceId(null);
      return;
    }

    audio.src = url;
    audio.currentTime = 0;
    setPlayingResourceId(resource.id);
    void audio.play().catch(() => setPlayingResourceId(null));
  };

  const previewButton = (resource: AssetResource, label: string) => {
    const playing = playingResourceId === resource.id;
    const previewLabel = playing
      ? t("pause_audio_preview", { label })
      : t("play_audio_preview", { label });
    return (
      <button
        type="button"
        aria-label={previewLabel}
        title={previewLabel}
        disabled={!urlFor(resource)}
        onClick={() => togglePreview(resource)}
        className="focus-ring grid h-9 w-9 shrink-0 place-items-center rounded-md outline-none transition-colors hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-40"
        style={{ color: playing ? "var(--color-accent-2)" : "var(--color-text-3)" }}
      >
        {playing
          ? <Pause aria-hidden className="h-4 w-4 fill-current" />
          : <Play aria-hidden className="h-4 w-4 fill-current" />}
      </button>
    );
  };

  if (!selected) return null;
  const selectedLabel = labelFor(selected, selectedIndex);

  return (
    <div ref={rootRef} className="relative">
      {/* Catalog voice samples do not include caption tracks. */}
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio
        ref={audioRef}
        className="hidden"
        preload="none"
        onEnded={() => setPlayingResourceId(null)}
        onError={() => setPlayingResourceId(null)}
      />
      <div
        className="flex w-full items-center gap-1 rounded-lg p-1"
        style={{
          background: "oklch(0.16 0.010 265 / 0.6)",
          border: "1px solid var(--color-hairline)",
          color: "var(--color-text)",
        }}
      >
        {previewButton(selected, selectedLabel)}
        <button
          type="button"
          aria-label={t("select_primary_audio", { label: selectedLabel })}
          aria-haspopup="dialog"
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          onClick={() => setOpen((current) => !current)}
          className="focus-ring flex min-w-0 flex-1 items-center gap-2 px-1.5 py-1 text-left outline-none"
        >
          <AudioLines aria-hidden className="h-4 w-4 shrink-0 text-text-4" />
          <span className="min-w-0 flex-1 truncate text-[12px]">{selectedLabel}</span>
          <ChevronDown aria-hidden className={`h-4 w-4 shrink-0 text-text-4 transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
      </div>
      {open && (
        <div
          id={panelId}
          role="dialog"
          aria-label={t("field.primary_audio")}
          className="absolute inset-x-0 top-full z-20 mt-1 max-h-64 overflow-y-auto rounded-lg border p-1 shadow-2xl"
          style={{ background: "oklch(0.17 0.010 265)", borderColor: "var(--color-hairline)" }}
        >
          {resources.map((resource, index) => {
            const label = labelFor(resource, index);
            const selectedOption = resource.id === value;
            return (
              <div key={resource.id} className="flex items-center gap-1 rounded-md hover:bg-white/5">
                {previewButton(resource, label)}
                <button
                  type="button"
                  aria-pressed={selectedOption}
                  onClick={() => {
                    onChange(resource.id);
                    setOpen(false);
                  }}
                  className="focus-ring flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-2 text-left outline-none"
                >
                  <span className="min-w-0 flex-1 truncate text-[12px] text-text-2">{label}</span>
                  {selectedOption && <Check aria-hidden className="h-4 w-4 shrink-0 text-accent" />}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ResourceRemovalList({
  resources,
  mediaType,
  onRemove,
}: {
  resources: AssetResource[];
  mediaType: "image" | "audio";
  onRemove: (resource: AssetResource) => void;
}) {
  const { t } = useTranslation("assets");
  const localResources = resources.filter((resource) => resource.origin === "local");
  if (!localResources.length) return null;
  return (
    <div className="flex flex-col gap-1.5">
      {localResources.map((resource, index) => {
        const label = mediaType === "image"
          ? t("local_image_option", { index: index + 1 })
          : t("local_audio_option", { index: index + 1 });
        return (
          <div
            key={resource.id}
            className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-[11px] text-text-3"
            style={{ background: "oklch(0.15 0.008 265 / 0.45)", border: "1px solid var(--color-hairline-soft)" }}
          >
            {mediaType === "image"
              ? <ImageIcon aria-hidden className="h-3.5 w-3.5 shrink-0" />
              : <AudioLines aria-hidden className="h-3.5 w-3.5 shrink-0" />}
            <span className="min-w-0 flex-1 truncate">{label}</span>
            <button
              type="button"
              aria-label={t("remove_resource", { name: label })}
              title={t("remove_resource", { name: label })}
              onClick={() => onRemove(resource)}
              className="focus-ring grid h-7 w-7 place-items-center rounded-md text-text-4 outline-none transition-colors hover:bg-red-500/10 hover:text-red-300"
            >
              <Trash2 aria-hidden className="h-3.5 w-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}

function PendingMediaList({
  items,
  mediaType,
  primaryId,
  onPrimary,
  onRemove,
}: {
  items: PendingMedia[];
  mediaType: "image" | "audio";
  primaryId: string | null;
  onPrimary: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  const { t } = useTranslation("assets");
  if (!items.length) return null;
  return (
    <div className="flex flex-col gap-1.5">
      {items.map((item) => {
        const primary = item.id === primaryId;
        return (
          <div
            key={item.id}
            className="flex items-center gap-2 rounded-lg p-2"
            style={{
              background: primary ? "var(--color-accent-dim)" : "oklch(0.15 0.008 265 / 0.45)",
              border: `1px solid ${primary ? "var(--color-accent-soft)" : "var(--color-hairline-soft)"}`,
            }}
          >
            {mediaType === "image" ? (
              <img
                src={item.previewUrl}
                alt={item.file.name}
                className="h-10 w-14 shrink-0 rounded-md object-cover"
              />
            ) : (
              <>
                {/* User-provided reference voices do not include caption tracks. */}
                {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
                <audio controls preload="metadata" src={item.previewUrl} className="h-8 w-32 shrink-0" />
              </>
            )}
            <span className="min-w-0 flex-1 truncate text-[11px] text-text-3" title={item.file.name}>
              {item.file.name}
            </span>
            <button
              type="button"
              aria-pressed={primary}
              aria-label={t("set_primary_resource", { name: item.file.name })}
              title={t("set_primary_resource", { name: item.file.name })}
              onClick={() => onPrimary(item.id)}
              className="focus-ring grid h-7 w-7 place-items-center rounded-md outline-none transition-colors hover:bg-white/5"
              style={{ color: primary ? "var(--color-accent-2)" : "var(--color-text-4)" }}
            >
              <Check aria-hidden className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              aria-label={t("remove_resource", { name: item.file.name })}
              title={t("remove_resource", { name: item.file.name })}
              onClick={() => onRemove(item.id)}
              className="focus-ring grid h-7 w-7 place-items-center rounded-md text-text-4 outline-none transition-colors hover:bg-red-500/10 hover:text-red-300"
            >
              <Trash2 aria-hidden className="h-3.5 w-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}

function FieldLabel({
  label,
  children,
}: {
  label: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span
        className="num text-[10px] uppercase"
        style={{
          color: "var(--color-text-4)",
          letterSpacing: "1.0px",
        }}
      >
        {label}
      </span>
      {children}
    </label>
  );
}

function FieldGroup({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span
        className="num text-[10px] uppercase"
        style={{ color: "var(--color-text-4)", letterSpacing: "1.0px" }}
      >
        {label}
      </span>
      {children}
    </div>
  );
}
