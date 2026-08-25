import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { API } from "@/api";
import { ConfigImportGate } from "@/components/config/ConfigImportGate";
import { useAuthStore } from "@/stores/auth-store";
import { useConfigStatusStore } from "@/stores/config-status-store";

describe("ConfigImportGate", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: true, isLoading: false });
    useConfigStatusStore.setState(useConfigStatusStore.getInitialState(), true);
  });

  it("does not open when configuration is ready", async () => {
    vi.spyOn(API, "getConfigImportStatus").mockResolvedValue({ enabled: true, ready: true, issues: [] });
    render(<ConfigImportGate />);
    await waitFor(() => expect(API.getConfigImportStatus).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens when configuration is missing and imports a dropped file", async () => {
    vi.spyOn(API, "getConfigImportStatus").mockResolvedValue({
      enabled: true,
      ready: false,
      issues: ["agent", "supabase"],
    });
    vi.spyOn(API, "importConfigFile").mockResolvedValue({ enabled: true, ready: true, issues: [] });
    vi.spyOn(useConfigStatusStore.getState(), "refresh").mockResolvedValue();

    render(<ConfigImportGate />);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("导入本地运行配置");

    const dropTarget = screen.getByText("将配置文件拖到这里").closest("button");
    const file = new File(["ARCREEL_CONFIG_BUNDLE=abc"], ".env.release", { type: "text/plain" });
    fireEvent.drop(dropTarget!, { dataTransfer: { files: [file] } });

    await waitFor(() => expect(API.importConfigFile).toHaveBeenCalledWith(file));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("rejects unrelated file types before upload", async () => {
    vi.spyOn(API, "getConfigImportStatus").mockResolvedValue({
      enabled: true,
      ready: false,
      issues: ["agent"],
    });
    const importSpy = vi.spyOn(API, "importConfigFile");
    render(<ConfigImportGate />);
    await screen.findByRole("dialog");

    const input = screen.getByLabelText("选择本地配置文件");
    fireEvent.change(input, { target: { files: [new File(["x"], "secret.txt")] } });

    expect(await screen.findByRole("alert")).toHaveTextContent("请选择 .env 或 .release 配置文件");
    expect(importSpy).not.toHaveBeenCalled();
  });
});
