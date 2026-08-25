import type { MentionCandidate } from "./MentionPicker";
import type { ProjectData } from "@/types";
import {
  SHEET_FIELD,
  type AssetKind,
  type MentionReferenceKind,
  type ReferenceKeyframe,
} from "@/types/reference-video";

/** Build the picker rows from project assets plus optional unit-owned keyframes. */
export function buildMentionCandidates(
  project: ProjectData | null,
  keyframes: ReferenceKeyframe[] = [],
): Record<MentionReferenceKind, MentionCandidate[]> {
  const buckets: Record<AssetKind, Record<string, unknown> | undefined> = {
    product: project?.products,
    character: project?.characters,
    scene: project?.scenes,
    prop: project?.props,
  };
  const candidates = {} as Record<MentionReferenceKind, MentionCandidate[]>;
  for (const kind of ["product", "character", "scene", "prop"] as const) {
    candidates[kind] = Object.entries(buckets[kind] ?? {}).map(([name, data]) => ({
      name,
      imagePath:
        (data as Partial<Record<(typeof SHEET_FIELD)[AssetKind], string>>)[SHEET_FIELD[kind]] ??
        null,
    }));
  }
  candidates.keyframe = keyframes.map((keyframe) => ({
    name: `关键分镜 ${keyframe.keyframe_id}`,
    imagePath: keyframe.image_path,
  }));
  return candidates;
}
