export type AssetType = "character" | "scene" | "prop";

export interface AssetResource {
  id: string;
  key: string;
  origin: "catalog" | "local";
  media_type: "image" | "audio";
  mime_type: string | null;
  path: string;
  byte_size: number | null;
  is_primary: boolean;
}

export interface Asset {
  id: string;
  type: AssetType;
  name: string;
  description: string;
  voice_style: string;
  image_path: string | null;
  audio_path: string | null;
  source_project: string | null;
  external_source?: string | null;
  external_id?: string | null;
  external_origin?: "official" | "user_shared" | null;
  external_version?: number | null;
  external_status?: "published" | "archived" | null;
  external_owner_id?: string | null;
  external_owner_name?: string | null;
  company_publish_state?: "publish" | "update" | "read_only_official" | "read_only_other";
  voice_id?: string | null;
  aliases?: string[];
  resources?: AssetResource[];
  updated_at: string | null;
}

export interface AssetCreatePayload {
  type: AssetType;
  name: string;
  description?: string;
  voice_style?: string;
  voice_id?: string;
  /** Legacy single-image caller support. New asset-library flows use images. */
  image?: File;
  images?: File[];
  audios?: File[];
  primary_image_index?: number;
  primary_audio_index?: number;
}

export interface AssetUpdatePayload {
  name?: string;
  description?: string;
  voice_style?: string;
  voice_id?: string;
}

export interface AssetResourceGroupUpdatePayload {
  name?: string;
  description?: string;
  voice_style?: string;
  voice_id?: string;
  images?: File[];
  audios?: File[];
  remove_resource_ids?: string[];
  primary_image_resource_id?: string;
  primary_audio_resource_id?: string;
  primary_image_upload_index?: number;
  primary_audio_upload_index?: number;
}
