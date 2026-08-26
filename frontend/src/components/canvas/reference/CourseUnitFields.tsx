import { useTranslation } from "react-i18next";
import type { ReferenceVideoUnit } from "@/types";

type CoursePatch = Pick<
  ReferenceVideoUnit,
  "unit_type" | "scenes" | "characters" | "props" | "presenters"
>;

interface Props {
  unit: ReferenceVideoUnit;
  sceneNames: string[];
  characterNames: string[];
  actorNames: string[];
  lecturerNames: string[];
  propNames: string[];
  disabled?: boolean;
  onPatch: (patch: Partial<CoursePatch>) => void | Promise<void>;
  onPatchBookends: (patch: Pick<CoursePatch, "scenes" | "characters" | "presenters">) => void | Promise<void>;
}

function MultiSelect({
  label,
  values,
  options,
  onChange,
  disabled,
}: {
  label: string;
  values: string[];
  options: string[];
  onChange: (values: string[]) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-[11px] text-[var(--color-text-4)]">
      <span>{label}</span>
      <select
        multiple
        value={values}
        disabled={disabled}
        onChange={(event) =>
          onChange(Array.from(event.currentTarget.selectedOptions, (option) => option.value))
        }
        className="focus-ring min-h-20 rounded-md border border-[var(--color-hairline)] bg-[oklch(0.19_0.011_265)] px-2 py-1.5 text-[11.5px] text-[var(--color-text-2)] disabled:opacity-60"
      >
        {options.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
    </label>
  );
}

function SingleSelect({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-[11px] text-[var(--color-text-4)]">
      <span>{label}</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.currentTarget.value)}
        className="focus-ring rounded-md border border-[var(--color-hairline)] bg-[oklch(0.19_0.011_265)] px-2 py-1.5 text-[11.5px] text-[var(--color-text-2)] disabled:opacity-60"
      >
        <option value="">—</option>
        {options.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
    </label>
  );
}

export function CourseUnitFields({
  unit,
  sceneNames,
  characterNames,
  actorNames,
  lecturerNames,
  propNames,
  disabled,
  onPatch,
  onPatchBookends,
}: Props) {
  const { t } = useTranslation("dashboard");
  const type = unit.unit_type ?? "story";
  const bookend = type === "opening" || type === "closing";
  const patchPeople = (patch: Partial<Pick<CoursePatch, "characters" | "presenters">>) => {
    if (bookend) {
      void onPatchBookends({
        scenes: unit.scenes ?? [],
        characters: patch.characters ?? unit.characters ?? [],
        presenters: patch.presenters ?? unit.presenters ?? [],
      });
    } else {
      void onPatch(patch);
    }
  };

  return (
    <section className="grid gap-3 border-t border-[var(--color-hairline-soft)] p-3 sm:grid-cols-2">
      <label className="flex flex-col gap-1 text-[11px] text-[var(--color-text-4)]">
        <span>{t("course_unit_type")}</span>
        <select
          value={type}
          disabled={disabled || bookend}
          onChange={(event) => void onPatch({ unit_type: event.currentTarget.value as CoursePatch["unit_type"] })}
          className="focus-ring rounded-md border border-[var(--color-hairline)] bg-[oklch(0.19_0.011_265)] px-2 py-1.5 text-[11.5px] text-[var(--color-text-2)] disabled:opacity-60"
        >
          {bookend ? (
            <option value={type}>
              {t(type === "opening" ? "course_unit_opening" : "course_unit_closing")}
            </option>
          ) : (
            <>
              <option value="story">{t("course_unit_story")}</option>
              <option value="explanation">{t("course_unit_explanation")}</option>
            </>
          )}
        </select>
      </label>

      {bookend ? (
        <SingleSelect
          label={t("course_unit_scenes")}
          value={unit.scenes?.[0] ?? ""}
          options={sceneNames}
          disabled={disabled}
          onChange={(scene) =>
            void onPatchBookends({
              scenes: scene ? [scene] : [],
              characters: unit.characters ?? [],
              presenters: unit.presenters ?? [],
            })
          }
        />
      ) : (
        <MultiSelect
          label={t("course_unit_scenes")}
          values={unit.scenes ?? []}
          options={sceneNames}
          disabled={disabled}
          onChange={(scenes) => void onPatch({ scenes })}
        />
      )}
      {(type === "story" || bookend) && (
        <MultiSelect
          label={t("course_unit_characters")}
          values={unit.characters ?? []}
          options={bookend ? characterNames : actorNames}
          disabled={disabled}
          onChange={(characters) => patchPeople({ characters })}
        />
      )}
      {(type === "explanation" || bookend) && (
        <MultiSelect
          label={t("course_unit_presenters")}
          values={unit.presenters ?? []}
          options={lecturerNames}
          disabled={disabled}
          onChange={(presenters) => patchPeople({ presenters })}
        />
      )}
      {type === "story" && (
        <MultiSelect
          label={t("course_unit_props")}
          values={unit.props ?? []}
          options={propNames}
          disabled={disabled}
          onChange={(props) => void onPatch({ props })}
        />
      )}
    </section>
  );
}
