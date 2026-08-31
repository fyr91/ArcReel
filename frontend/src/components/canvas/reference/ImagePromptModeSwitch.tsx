import { useTranslation } from "react-i18next";
import type { ImagePromptMode } from "./usePersistentImagePrompt";

interface ImagePromptModeSwitchProps {
  mode: ImagePromptMode;
  onChange: (mode: ImagePromptMode) => void;
  disabled?: boolean;
  label: string;
}

export function ImagePromptModeSwitch({
  mode,
  onChange,
  disabled = false,
  label,
}: ImagePromptModeSwitchProps) {
  const { t } = useTranslation("dashboard");
  const options: Array<{ value: ImagePromptMode; text: string }> = [
    { value: "description", text: t("reference_image_prompt_mode_description") },
    { value: "full_prompt", text: t("reference_image_prompt_mode_full") },
  ];

  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex rounded-md border border-[var(--color-hairline-soft)] bg-black/15 p-0.5 normal-case tracking-normal"
    >
      {options.map((option) => {
        const active = option.value === mode;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            className={`focus-ring rounded px-2 py-1 text-[10px] font-medium transition-colors disabled:opacity-50 ${
              active
                ? "bg-[var(--color-accent-dim)] text-[var(--color-accent-2)]"
                : "text-[var(--color-text-4)] hover:text-[var(--color-text-2)]"
            }`}
          >
            {option.text}
          </button>
        );
      })}
    </div>
  );
}

interface FullPromptTextareaProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  ariaLabel: string;
}

export function FullPromptTextarea({ value, onChange, disabled, ariaLabel }: FullPromptTextareaProps) {
  const { t } = useTranslation("dashboard");
  return (
    <textarea
      value={value}
      onChange={(event) => onChange(event.target.value)}
      disabled={disabled}
      aria-label={ariaLabel}
      placeholder={t("reference_image_full_prompt_placeholder")}
      className="focus-ring h-full w-full resize-none overflow-auto rounded-lg border border-[var(--color-hairline-soft)] bg-[oklch(0.195_0.003_160_/_0.4)] px-3 py-2 font-mono text-xs font-normal leading-5 normal-case tracking-normal text-[var(--color-text)] outline-none disabled:cursor-not-allowed disabled:opacity-60"
    />
  );
}
