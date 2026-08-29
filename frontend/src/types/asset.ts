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
}

export interface AssetUpdatePayload {
  name?: string;
  description?: string;
  voice_style?: string;
}
