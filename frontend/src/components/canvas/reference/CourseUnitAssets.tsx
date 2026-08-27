import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import type { Character, ProjectData, Prop, Scene } from "@/types";
import {
  buildMentionLookup,
  dialogueSpeakers,
  extractMentions,
  normalizeAssetName,
} from "@/utils/reference-mentions";

type PreviewKind = "scene" | "character" | "prop";

interface AssetPreview {
  name: string;
  imagePath: string | null;
}

type PreviewGroups = Record<PreviewKind, AssetPreview[]>;

interface Props {
  projectName: string;
  project: ProjectData | null;
  text: string;
}

function normalizedEntries<T>(bucket: Record<string, T> | undefined): Map<string, [string, T]> {
  return new Map(
    Object.entries(bucket ?? {}).map(([name, value]) => [normalizeAssetName(name), [name, value]]),
  );
}

function characterImage(character: Character): string | null {
  for (const path of [
    character.lecturer_portrait,
    character.character_sheet,
    character.reference_image,
  ]) {
    const normalizedPath = path?.trim();
    if (normalizedPath) return normalizedPath;
  }
  return null;
}

/**
 * Read-time projection for the course editor's informational asset strip.
 *
 * Visual mentions follow the same parser as video reference projection. Dialogue speakers are
 * added to the character group because they are relevant to the unit even when their speaker-slot
 * mention deliberately does not inject a visual reference image into the provider request.
 */
export function deriveCourseUnitAssets(
  text: string,
  project: ProjectData | null,
): PreviewGroups {
  const groups: PreviewGroups = { scene: [], character: [], prop: [] };
  if (!project) return groups;

  const lookup = buildMentionLookup(project);
  const scenes = normalizedEntries<Scene>(project.scenes);
  const characters = normalizedEntries<Character>(project.characters);
  const props = normalizedEntries<Prop>(project.props);
  const seen = new Set<string>();
  const names = [...extractMentions(text), ...dialogueSpeakers(text)];

  for (const writtenName of names) {
    const key = normalizeAssetName(writtenName);
    const kind = lookup[key];
    if (kind !== "scene" && kind !== "character" && kind !== "prop") continue;
    const identity = `${kind}:${key}`;
    if (seen.has(identity)) continue;
    seen.add(identity);

    if (kind === "scene") {
      const entry = scenes.get(key);
      if (entry) groups.scene.push({ name: entry[0], imagePath: entry[1].scene_sheet ?? null });
    } else if (kind === "character") {
      const entry = characters.get(key);
      if (entry) groups.character.push({ name: entry[0], imagePath: characterImage(entry[1]) });
    } else {
      const entry = props.get(key);
      if (entry) groups.prop.push({ name: entry[0], imagePath: entry[1].prop_sheet ?? null });
    }
  }

  return groups;
}

function AssetGroup({
  label,
  items,
  projectName,
  kind,
  emptyLabel,
}: {
  label: string;
  items: AssetPreview[];
  projectName: string;
  kind: PreviewKind;
  emptyLabel: string;
}) {
  const fallbackColor = {
    scene: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
    character: "border-sky-400/30 bg-sky-400/10 text-sky-200",
    prop: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  }[kind];

  return (
    <div className="min-w-0" data-testid={`course-assets-${kind}`}>
      <h3 className="mb-2 text-[11px] font-normal text-[var(--color-text-4)]">{label}</h3>
      {items.length > 0 ? (
        <ul className="m-0 flex list-none flex-wrap gap-x-3 gap-y-2 p-0">
          {items.map((item) => {
            const previewUrl = item.imagePath
              ? API.getFileUrl(projectName, item.imagePath)
              : null;
            return (
              <li key={item.name} className="flex min-w-0 items-center gap-2">
                {previewUrl ? (
                  <img
                    src={previewUrl}
                    alt=""
                    aria-hidden="true"
                    loading="lazy"
                    className="h-9 w-9 shrink-0 rounded-full border border-[var(--color-hairline)] object-cover"
                  />
                ) : (
                  <span
                    aria-hidden="true"
                    className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full border text-xs font-semibold ${fallbackColor}`}
                  >
                    {Array.from(item.name)[0] ?? "·"}
                  </span>
                )}
                <span
                  className="max-w-28 truncate text-[11.5px] text-[var(--color-text-2)]"
                  title={item.name}
                >
                  {item.name}
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        <span className="text-[11.5px] text-[var(--color-text-4)]">{emptyLabel}</span>
      )}
    </div>
  );
}

export function CourseUnitAssets({ projectName, project, text }: Props) {
  const { t } = useTranslation("dashboard");
  const groups = useMemo(() => deriveCourseUnitAssets(text, project), [project, text]);

  return (
    <section
      aria-label={t("course_unit_related_assets")}
      className="grid gap-3 border-t border-[var(--color-hairline-soft)] p-3 sm:grid-cols-3"
    >
      <AssetGroup
        label={t("course_unit_scenes")}
        items={groups.scene}
        projectName={projectName}
        kind="scene"
        emptyLabel={t("course_unit_assets_empty")}
      />
      <AssetGroup
        label={t("course_unit_characters")}
        items={groups.character}
        projectName={projectName}
        kind="character"
        emptyLabel={t("course_unit_assets_empty")}
      />
      <AssetGroup
        label={t("course_unit_props")}
        items={groups.prop}
        projectName={projectName}
        kind="prop"
        emptyLabel={t("course_unit_assets_empty")}
      />
    </section>
  );
}
