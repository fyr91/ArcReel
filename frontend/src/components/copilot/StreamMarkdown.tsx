import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ComponentProps,
  type ComponentType,
  type MouseEvent,
} from "react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { errMsg, voidCall } from "@/utils/async";

// ---------------------------------------------------------------------------
// StreamMarkdown – lazy-loads the Streamdown component from the `streamdown`
// package and renders markdown content.  Falls back to a plain whitespace-
// preserving <div> while the library is loading.
// ---------------------------------------------------------------------------

let streamdownPromise: Promise<ComponentType<Record<string, unknown>> | null> | null =
  null;

async function loadStreamdownComponent(): Promise<ComponentType<Record<string, unknown>> | null> {
  if (streamdownPromise) return streamdownPromise;

  streamdownPromise = import("streamdown")
    .then((mod) => {
      // The named export `Streamdown` is a MemoExoticComponent
      const Comp = (mod as Record<string, unknown>).Streamdown ??
        (mod as Record<string, unknown>).default ??
        null;
      return Comp as ComponentType<Record<string, unknown>> | null;
    })
    .catch((error) => {
      console.warn("Failed to load Streamdown:", error);
      return null;
    });

  return streamdownPromise;
}

interface StreamMarkdownProps {
  content: string;
  projectName?: string;
}

// Must match server.services.project_path_links.PROJECT_PATH_LINK_ROUTE.
const PROJECT_PATH_LINK_ROUTE = "/__arcreel_open_project_path__";

export function projectPathFromHref(href: string): string | null {
  try {
    const url = new URL(href, globalThis.location.origin);
    if (url.origin !== globalThis.location.origin || url.pathname !== PROJECT_PATH_LINK_ROUTE) {
      return null;
    }
    return url.searchParams.has("path") ? url.searchParams.get("path") : null;
  } catch {
    return null;
  }
}

export function StreamMarkdown({ content, projectName }: StreamMarkdownProps) {
  const { t } = useTranslation("dashboard");
  const [StreamdownComponent, setStreamdownComponent] =
    useState<ComponentType<Record<string, unknown>> | null>(null);

  useEffect(() => {
    let mounted = true;

    voidCall(loadStreamdownComponent().then((component) => {
      if (!mounted || !component) return;
      setStreamdownComponent(() => component);
    }));

    return () => {
      mounted = false;
    };
  }, []);

  const handleProjectPathClick = useCallback((event: MouseEvent<HTMLAnchorElement>, href: string) => {
    const relativePath = projectPathFromHref(href);
    if (relativePath === null) return;

    event.preventDefault();
    if (!projectName) {
      useAppStore.getState().pushToast(t("project_path_no_active_project"), "error");
      return;
    }

    voidCall(
      API.revealProjectPath(projectName, relativePath).then((result) => {
        useAppStore.getState().pushToast(
          t("project_path_revealed", { path: result.relative_path }),
          "success",
        );
      }),
      (error) => {
        useAppStore.getState().pushToast(
          t("project_path_reveal_failed", { message: errMsg(error) }),
          "error",
        );
      },
    );
  }, [projectName, t]);

  const markdownComponents = useMemo(() => ({
    a: ({ href, onClick, node: _node, children, ...props }: ComponentProps<"a"> & { node?: unknown }) => (
      <a
        {...props}
        href={href}
        onClick={(event) => {
          onClick?.(event);
          if (!event.defaultPrevented) handleProjectPathClick(event, href ?? "");
        }}
      >
        {children}
      </a>
    ),
  }), [handleProjectPathClick]);

  if (!StreamdownComponent) {
    return <div className="whitespace-pre-wrap break-words">{content || ""}</div>;
  }

  return (
    <StreamdownComponent
      className="markdown-body text-sm leading-6"
      components={markdownComponents}
      parseIncompleteMarkdown={true}
    >
      {String(content || "")}
    </StreamdownComponent>
  );
}
