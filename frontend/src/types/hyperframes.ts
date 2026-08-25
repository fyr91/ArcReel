import type { PresentationVariant } from "./presentation";

export type HyperframesStudioStatus = "stopped" | "ready";
export type HyperframesEditingState = "assembly_draft" | "edited" | "unknown";

export interface HyperframesEditingAnalysis {
  state: HyperframesEditingState;
  picture_edit_count: number;
  source_unit_count: number;
  video_clip_count: number;
  timing_changes: number;
  split_ranges: number;
  reordered_units: number;
  overlapping_handoffs: number;
  retimed_clips: number;
  visual_treatments: number;
  audio_automations: number;
}

export interface HyperframesWorkspaceStatus {
  project_name: string;
  episode: number;
  exists: boolean;
  workspace_path: string | null;
  composition_path: string | null;
  manifest_path: string | null;
  editing_state?: HyperframesEditingState | null;
  editing_analysis?: HyperframesEditingAnalysis | null;
  studio_status: HyperframesStudioStatus;
  studio_url: string | null;
}

export interface PrepareHyperframesWorkspaceRequest {
  narration_delivery: PresentationVariant;
}

export interface GenerateHyperframesBgmRequest {
  direction: string;
  seed?: number;
}

export interface HyperframesBgmTaskResponse {
  task_id: string;
  status: string;
  resource_id: string;
  deduped?: boolean;
}

export interface HyperframesAutoEditOptions {
  narrationDelivery: PresentationVariant;
  instruction: string;
  backgroundMusic: boolean;
}
