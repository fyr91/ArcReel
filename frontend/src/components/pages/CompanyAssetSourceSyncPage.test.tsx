import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import { API } from "@/api";
import type { CompanyCatalogAsset } from "@/types";
import { CompanyAssetSourceSyncPage } from "./CompanyAssetSourceSyncPage";

function renderPage() {
  const location = memoryLocation({ path: "/app/assets/source-sync" });
  return render(
    <Router hook={location.hook} searchHook={location.searchHook}>
      <CompanyAssetSourceSyncPage />
    </Router>,
  );
}

function asset(overrides: Partial<CompanyCatalogAsset> = {}): CompanyCatalogAsset {
  return {
    id: "6bf51491-016c-42ed-bd35-458ca670b4f4",
    asset_type: "character",
    origin: "official",
    status: "published",
    version: 2,
    name: "测试人物",
    description: "服务器上的测试数据",
    owner_name: null,
    source_name: "人物资产渠道",
    files: [],
    created_at: "2026-08-29T00:00:00Z",
    updated_at: "2026-08-29T01:00:00Z",
    ...overrides,
  };
}

describe("CompanyAssetSourceSyncPage central catalog management", () => {
  beforeEach(() => {
    vi.spyOn(API, "getCompanyAssetSourceSyncDashboard").mockResolvedValue({ sources: [], runs: [] });
    vi.spyOn(API, "listCompanyCatalogAssets").mockResolvedValue({
      items: [asset()],
      total: 1,
      totals: { character: 1, scene: 0, prop: 0 },
    });
    vi.spyOn(API, "deleteCompanyCatalogAsset").mockResolvedValue({
      asset_id: asset().id,
      name: asset().name,
      asset_type: "character",
      origin: "official",
      queued_file_count: 0,
    });
    vi.spyOn(API, "getCompanyCatalogAssetPreview").mockResolvedValue(new Blob());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("queries the Supabase catalog and hard-deletes the selected central asset", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "公司资产总库" })).toBeInTheDocument();
    expect(await screen.findByText("测试人物")).toBeInTheDocument();
    expect(screen.getByText("人物资产渠道")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("searchbox", { name: "搜索服务器资产" }), {
      target: { value: "测试" },
    });
    await waitFor(() => {
      expect(API.listCompanyCatalogAssets).toHaveBeenLastCalledWith(
        expect.objectContaining({ q: "测试", limit: 24, offset: 0 }),
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "删除测试人物" }));
    expect(await screen.findByText(/将从服务器 Supabase 永久删除/)).toBeInTheDocument();
    expect(screen.getByText(/下次监控同步时可能重新出现/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "永久删除" }));

    await waitFor(() => expect(API.deleteCompanyCatalogAsset).toHaveBeenCalledWith(asset().id));
    await waitFor(() => expect(API.listCompanyCatalogAssets).toHaveBeenCalledTimes(3));
  });
});
