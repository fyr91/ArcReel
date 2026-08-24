import {
  Fragment,
  useCallback,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { MENTION_PICKER_DEFAULT_ID, MentionPicker, type MentionCandidate } from "./MentionPicker";
import { ASSET_COLORS, assetColor } from "./asset-colors";
import { useUnitPromptHighlight, type MentionLookup, type Token } from "@/hooks/useUnitPromptHighlight";
import { MENTION_RE } from "@/utils/reference-mentions";
import type { MentionReferenceKind } from "@/types/reference-video";

const MENTION_SPAN_CLASS = "rounded-sm";

function renderHighlightedTokens(
  tokens: Token[],
  caretOffset: number | null,
  setAnchorEl: (el: HTMLSpanElement | null) => void,
  voiceoverLabel: string,
): ReactNode {
  const out: ReactNode[] = [];
  let acc = 0;
  const anchorEl = caretOffset !== null ? (
    <span
      key="__caret_anchor__"
      ref={setAnchorEl}
      aria-hidden="true"
      className="inline-block h-[1em] w-0 align-baseline"
    />
  ) : null;

  const renderPiece = (token: Token, sliceText: string, key: string): ReactNode => {
    if (sliceText.length === 0) return null;
    if (token.kind === "mention") {
      const palette = assetColor(token.assetKind);
      return (
        <span key={key} className={`${MENTION_SPAN_CLASS} ${palette.textClass} ${palette.bgClass}`}>
          {sliceText}
        </span>
      );
    }
    if (token.kind === "speech") {
      const palette = assetColor(token.speakerKind);
      return (
        <span
          key={key}
          className={`${MENTION_SPAN_CLASS} bg-[oklch(1_0_0_/_0.06)] ${token.speaker ? palette.textClass : ""}`}
          title={token.speaker || voiceoverLabel}
        >
          {sliceText}
        </span>
      );
    }
    return <span key={key}>{sliceText}</span>;
  };

  let inserted = false;
  tokens.forEach((token, index) => {
    const nextAcc = acc + token.text.length;
    if (!inserted && caretOffset !== null && caretOffset >= acc && caretOffset <= nextAcc) {
      const local = caretOffset - acc;
      out.push(
        <Fragment key={`pre-${index}`}>
          {renderPiece(token, token.text.slice(0, local), `pre-${index}`)}
        </Fragment>,
      );
      if (anchorEl) out.push(anchorEl);
      out.push(
        <Fragment key={`post-${index}`}>
          {renderPiece(token, token.text.slice(local), `post-${index}`)}
        </Fragment>,
      );
      inserted = true;
    } else {
      out.push(
        <Fragment key={`token-${index}`}>
          {renderPiece(token, token.text, `token-${index}`)}
        </Fragment>,
      );
    }
    acc = nextAcc;
  });
  if (!inserted && anchorEl && caretOffset !== null && caretOffset >= acc) out.push(anchorEl);
  return out;
}

export interface MentionTextareaProps {
  value: string;
  onChange: (next: string) => void;
  lookup: MentionLookup;
  candidates: Partial<Record<MentionReferenceKind, MentionCandidate[]>>;
  projectName: string;
  ariaLabel: string;
  placeholder?: string;
  disabled?: boolean;
  /** Fill an existing flex area; otherwise grow vertically with the manuscript. */
  fill?: boolean;
  className?: string;
}

/** Shared manuscript editor for persisted `@[asset]` mentions. */
export function MentionTextarea({
  value,
  onChange,
  lookup,
  candidates,
  projectName,
  ariaLabel,
  placeholder,
  disabled = false,
  fill = false,
  className,
}: MentionTextareaProps) {
  const { t } = useTranslation("dashboard");
  const taRef = useRef<HTMLTextAreaElement>(null);
  const preRef = useRef<HTMLPreElement>(null);
  const [anchorEl, setAnchorEl] = useState<HTMLSpanElement | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const [activeOptionId, setActiveOptionId] = useState<string | null>(null);
  const [atStart, setAtStart] = useState<number | null>(null);
  const instanceId = useId().replace(/:/g, "");
  const listboxId = `${MENTION_PICKER_DEFAULT_ID}-${instanceId}`;
  const unknownDescriptionId = `reference-editor-unknown-desc-${instanceId}`;

  const tokens = useUnitPromptHighlight(value, lookup);
  const voiceoverLabel = t("script_highlight_voiceover");
  const staticHighlightedNodes = useMemo(
    () => renderHighlightedTokens(tokens, null, () => {}, voiceoverLabel),
    [tokens, voiceoverLabel],
  );
  const unknownMentions = useMemo(() => {
    const seen = new Set<string>();
    const names: string[] = [];
    for (const token of tokens) {
      if (token.kind === "mention" && token.assetKind === "unknown" && !seen.has(token.name)) {
        seen.add(token.name);
        names.push(token.name);
      }
    }
    return names;
  }, [tokens]);

  const resize = useCallback(() => {
    if (fill) return;
    const textarea = taRef.current;
    if (!textarea || textarea.scrollHeight === 0) return;
    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, [fill]);

  useLayoutEffect(() => {
    resize();
  }, [resize, value]);

  const closePicker = useCallback(() => {
    setPickerOpen(false);
    setPickerQuery("");
    setAtStart(null);
    setActiveOptionId(null);
  }, []);

  const updatePickerFromCursor = useCallback((nextValue: string, cursor: number) => {
    let index = cursor - 1;
    while (index >= 0) {
      const character = nextValue[index];
      if (character === "@") {
        const previous = nextValue[index - 1];
        if (index === 0 || !/\w/.test(previous ?? "")) {
          const rawQuery = nextValue.slice(index + 1, cursor);
          const isWrapped = rawQuery.startsWith("[");
          if (!isWrapped && !/^[\w\u4e00-\u9fff]*$/.test(rawQuery)) break;
          setAtStart(index);
          setPickerQuery(isWrapped ? rawQuery.slice(1) : rawQuery);
          setPickerOpen(true);
          return;
        }
        break;
      }
      if (character === "]" || /\s/.test(character)) break;
      index -= 1;
    }
    setAtStart(null);
    setPickerOpen(false);
    setPickerQuery("");
  }, []);

  const handleChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    const next = event.target.value;
    onChange(next);
    updatePickerFromCursor(next, event.target.selectionStart ?? next.length);
  };

  const handleCursorUpdate = (event: React.SyntheticEvent<HTMLTextAreaElement>) => {
    const textarea = event.currentTarget;
    updatePickerFromCursor(textarea.value, textarea.selectionStart ?? textarea.value.length);
  };

  const handleKeyDown = useCallback((event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Backspace") return;
    const textarea = event.currentTarget;
    const start = textarea.selectionStart ?? 0;
    const end = textarea.selectionEnd ?? 0;
    if (start !== end) return;
    const scanFrom = Math.max(0, start - 64);
    const slice = textarea.value.slice(scanFrom, start);
    for (const match of slice.matchAll(MENTION_RE)) {
      const absoluteStart = scanFrom + (match.index ?? 0);
      const absoluteEnd = absoluteStart + match[0].length;
      if (absoluteEnd === start) {
        event.preventDefault();
        textarea.setSelectionRange(absoluteStart, absoluteEnd);
        return;
      }
    }
  }, []);

  const handlePickerSelect = useCallback(
    (reference: { type: MentionReferenceKind; name: string }) => {
      const textarea = taRef.current;
      const start = atStart;
      if (!textarea || start === null) {
        closePicker();
        return;
      }
      const before = value.slice(0, start);
      const cursor = textarea.selectionStart ?? value.length;
      const insert = `@[${reference.name}] `;
      const next = before + insert + value.slice(cursor);
      onChange(next);
      closePicker();
      requestAnimationFrame(() => {
        textarea.focus();
        const position = before.length + insert.length;
        textarea.setSelectionRange(position, position);
      });
    },
    [atStart, closePicker, onChange, value],
  );

  const handleScroll = () => {
    if (!preRef.current || !taRef.current) return;
    preRef.current.scrollTop = taRef.current.scrollTop;
    preRef.current.scrollLeft = taRef.current.scrollLeft;
  };

  return (
    <div className={className}>
      <div className={`relative rounded-md border border-gray-800 bg-gray-950/60 ${fill ? "h-full min-h-0" : "min-h-24"}`}>
        <pre
          ref={preRef}
          aria-hidden
          className="pointer-events-none absolute inset-0 m-0 overflow-hidden whitespace-pre-wrap break-words p-3 font-mono text-sm leading-6"
        >
          {pickerOpen
            ? renderHighlightedTokens(tokens, atStart, setAnchorEl, voiceoverLabel)
            : staticHighlightedNodes}
          {value.endsWith("\n") ? "\u200b" : null}
        </pre>

        <textarea
          ref={taRef}
          value={value}
          onChange={handleChange}
          onInput={resize}
          onKeyUp={handleCursorUpdate}
          onKeyDown={handleKeyDown}
          onClick={handleCursorUpdate}
          onBlur={closePicker}
          onScroll={handleScroll}
          disabled={disabled}
          rows={fill ? undefined : 4}
          role="combobox"
          aria-expanded={pickerOpen}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={pickerOpen && activeOptionId ? activeOptionId : undefined}
          aria-describedby={unknownMentions.length > 0 ? unknownDescriptionId : undefined}
          placeholder={placeholder}
          aria-label={ariaLabel}
          spellCheck={false}
          className={`relative block w-full resize-none bg-transparent p-3 font-mono text-sm leading-6 text-transparent caret-gray-200 placeholder:text-gray-600 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60 ${
            fill ? "h-full" : "min-h-24 overflow-hidden"
          }`}
        />

        {pickerOpen && anchorEl && !disabled && (
          <MentionPicker
            open
            query={pickerQuery}
            candidates={candidates}
            projectName={projectName}
            anchorElement={anchorEl}
            listboxId={listboxId}
            onSelect={handlePickerSelect}
            onClose={closePicker}
            onActiveChange={setActiveOptionId}
          />
        )}
      </div>

      {unknownMentions.length > 0 && (
        <div
          id={unknownDescriptionId}
          role="status"
          aria-live="polite"
          className="mt-2 flex flex-wrap gap-1"
        >
          <span className="sr-only">{t("reference_editor_unknown_mentions_label")}: </span>
          {unknownMentions.map((name) => {
            const palette = ASSET_COLORS.unknown;
            return (
              <span
                key={name}
                className={`rounded border px-2 py-0.5 text-[11px] ${palette.textClass} ${palette.bgClass} ${palette.borderClass}`}
              >
                {t("reference_editor_unknown_mention", { name })}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
