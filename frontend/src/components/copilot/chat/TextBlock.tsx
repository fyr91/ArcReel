import { StreamMarkdown } from "../StreamMarkdown";

// ---------------------------------------------------------------------------
// TextBlock – renders plain text / markdown content via StreamMarkdown.
// ---------------------------------------------------------------------------

interface TextBlockProps {
  text?: string;
  projectName?: string;
}

export function TextBlock({ text, projectName }: TextBlockProps) {
  if (!text) {
    return null;
  }

  return <StreamMarkdown content={text} projectName={projectName} />;
}
