export interface SystemConfigSettings {
  default_video_backend: string;
  default_video_backend_i2v?: string;
  default_video_backend_r2v?: string;
  default_image_backend: string;
  default_image_backend_t2i?: string;
  default_image_backend_i2i?: string;
  default_text_backend: string;
  default_audio_backend?: string;
  narration_voice?: string;
  narration_speed?: number | null;
  text_backend_simple: string;
  text_backend_complex: string;
  video_generate_audio: boolean;
  anthropic_api_key: { is_set: boolean; masked: string | null };
  anthropic_base_url: string;
  anthropic_model: string;
  anthropic_default_haiku_model: string;
  anthropic_default_opus_model: string;
  anthropic_default_sonnet_model: string;
  claude_code_subagent_model: string;
  agent_session_cleanup_delay_seconds: number;
  agent_max_concurrent_sessions: number;
  croco_characters_api_url?: string;
  croco_characters_api_token?: { is_set: boolean; masked: string | null };
  croco_characters_management_source?: string | null;
  model_settings?: Record<string, { resolution?: string | null }>;
}

export interface SystemConfigOptions {
  video_backends: string[];
  image_backends: string[];
  text_backends: string[];
  audio_backends?: string[];
  provider_names?: Record<string, string>;
}

export interface GetSystemConfigResponse {
  settings: SystemConfigSettings;
  options: SystemConfigOptions;
}

/** 能力桶键（docs/adr/0054）。代码内部术语，界面文案不直接呈现。 */
export type CapabilityBucket = "t2i" | "i2i" | "i2v" | "r2v";

/** 单一 media_type 的候选：默认层全量 + 各能力桶按能力过滤后的子集。 */
export interface MediaCandidates {
  default: string[];
  buckets: Partial<Record<CapabilityBucket, string[]>>;
}

export interface ModelCandidatesResponse {
  image: MediaCandidates;
  video: MediaCandidates;
  /** 仅含自定义供应商的显示名；内置供应商名由前端按 provider_id 本地化。 */
  provider_names: Record<string, string>;
}

/** A request-scoped image backend override. Empty means “follow project default”. */
export interface ImageModelSelection {
  imageProvider?: string;
  imageModel?: string;
}

export interface SystemVersionReleaseInfo {
  version: string;
  tag_name: string;
  name: string;
  body: string;
  html_url: string;
  published_at: string;
}

export interface GetSystemVersionResponse {
  current: { version: string };
  latest: SystemVersionReleaseInfo | null;
  has_update: boolean;
  checked_at: string;
  update_check_error: string | null;
}

/** 首次使用引导的「已看过」状态 —— 实例级，未设置视为未看过。 */
export interface OnboardingStatus {
  seen: boolean;
}

export interface SystemConfigPatch {
  default_video_backend?: string;
  default_video_backend_i2v?: string;
  default_video_backend_r2v?: string;
  default_image_backend?: string;
  default_image_backend_t2i?: string;
  default_image_backend_i2i?: string;
  default_text_backend?: string;
  default_audio_backend?: string;
  narration_voice?: string;
  narration_speed?: number | null;
  text_backend_simple?: string;
  text_backend_complex?: string;
  video_generate_audio?: boolean;
  anthropic_api_key?: string;
  anthropic_base_url?: string;
  anthropic_model?: string;
  anthropic_default_haiku_model?: string;
  anthropic_default_opus_model?: string;
  anthropic_default_sonnet_model?: string;
  claude_code_subagent_model?: string;
  agent_session_cleanup_delay_seconds?: number;
  agent_max_concurrent_sessions?: number;
  croco_characters_api_url?: string;
  croco_characters_api_token?: string;
  model_settings?: Record<string, { resolution?: string | null }>;
}

export interface CharacterCatalogSyncResult {
  publishVersion: { id: string; name: string; activatedAt: string };
  remoteCharacters: number;
  added: number;
  updated: number;
  unchanged: number;
  assetsDownloaded: number;
}

export interface CharacterCatalogSyncJob {
  job_id: string;
  job_type: "character_catalog_sync";
  status: "queued" | "running" | "succeeded" | "failed";
  phase: "queued" | "fetching_catalog" | "syncing_characters" | "completed" | "failed";
  progress_current: number;
  progress_total: number;
  result: CharacterCatalogSyncResult | null;
  error_code: string | null;
  error_detail: string | null;
  error_message: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface CompanyAssetSyncResult {
  added: number;
  updated: number;
  archived: number;
  unchanged: number;
  assetsDownloaded: number;
}

export interface CompanyAssetSyncJob {
  job_id: string;
  job_type: `company_asset_sync:${"character" | "scene" | "prop"}`;
  owner_id: string;
  payload: { asset_type: "character" | "scene" | "prop"; trigger: string } | null;
  status: "queued" | "running" | "succeeded" | "failed";
  phase: string;
  progress_current: number;
  progress_total: number;
  result: CompanyAssetSyncResult | null;
  error_code: string | null;
  error_detail: string | null;
  error_message: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface CompanyAssetSyncSource {
  id: string;
  source_key: string;
  display_name: string;
  asset_type: "character" | "scene" | "prop";
  adapter: string;
  enabled: boolean;
  paused: boolean;
  interval_seconds: number;
  next_run_at: string | null;
  last_run_at: string | null;
  last_success_at: string | null;
  last_status: string | null;
  last_error: string | null;
}

export interface CompanyAssetSourceSyncRun {
  id: string;
  source_id: string;
  source_key: string;
  display_name: string;
  asset_type: "character" | "scene" | "prop";
  trigger_kind: "schedule" | "manual" | "retry";
  status: "queued" | "running" | "cancelling" | "cancelled" | "succeeded" | "failed";
  imported_count: number;
  updated_count: number;
  unchanged_count: number;
  archived_count: number;
  error_code: string | null;
  error_detail: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface CompanyAssetSourceSyncDashboard {
  sources: CompanyAssetSyncSource[];
  runs: CompanyAssetSourceSyncRun[];
}

export interface CompanyCatalogAssetFile {
  id: string;
  key: string;
  role: string;
  media_type: "image" | "audio";
  mime_type: string | null;
  bucket_id: string;
  object_path: string;
  byte_size: number | null;
  sha256: string | null;
  revision: string | null;
  sort_order: number;
  source_fields: string[];
}

export interface CompanyCatalogAsset {
  id: string;
  asset_type: "character" | "scene" | "prop";
  origin: "official" | "user_shared";
  status: "published" | "archived";
  version: number;
  name: string;
  description: string;
  owner_name: string | null;
  source_name: string | null;
  files: CompanyCatalogAssetFile[];
  created_at: string;
  updated_at: string;
}

export interface CompanyCatalogAssetPage {
  items: CompanyCatalogAsset[];
  total: number;
  totals: Record<"character" | "scene" | "prop", number>;
}

export interface CompanyCatalogAssetDeleteResult {
  asset_id: string;
  name: string;
  asset_type: "character" | "scene" | "prop";
  origin: "official" | "user_shared";
  queued_file_count: number;
}
