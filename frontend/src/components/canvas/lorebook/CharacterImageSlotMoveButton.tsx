import { useState } from "react";
import { ArrowUpDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { errMsg } from "@/utils/async";

interface CharacterImageSlotMoveButtonProps {
  projectName: string;
  characterName: string;
  direction: "main-to-reference" | "reference-to-main";
  onReload?: () => void | Promise<unknown>;
  busy?: boolean;
}

/** Move the card's active image between its main and reference slots. */
export function CharacterImageSlotMoveButton({
  projectName,
  characterName,
  direction,
  onReload,
  busy = false,
}: CharacterImageSlotMoveButtonProps) {
  const { t } = useTranslation("assets");
  const [submitting, setSubmitting] = useState(false);
  const label = direction === "main-to-reference"
    ? t("switch_to_reference_image")
    : t("switch_to_main_image");

  const move = async () => {
    setSubmitting(true);
    try {
      if (direction === "main-to-reference") {
        await API.moveCharacterMainToReference(projectName, characterName);
      } else {
        await API.moveCharacterReferenceToMain(projectName, characterName);
      }
      await onReload?.();
    } catch (error) {
      useAppStore.getState().pushToast(errMsg(error), "error");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <button
      type="button"
      disabled={busy || submitting}
      onClick={() => { void move(); }}
      aria-label={label}
      title={label}
      className="focus-ring inline-flex h-7 w-7 items-center justify-center rounded-md text-[var(--color-text-3)] transition-colors hover:bg-[oklch(1_0_0_/_0.05)] hover:text-[var(--color-text)] disabled:cursor-not-allowed disabled:opacity-40"
    >
      <ArrowUpDown className="h-3.5 w-3.5" />
    </button>
  );
}
