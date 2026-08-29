import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { AssetCard } from "./AssetCard";

// Mock i18next
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, string>) => (
      key === "shared_by_read_only" ? `shared by ${values?.name}` : key
    ),
    i18n: { language: "en" },
  }),
}));

const asset = {
  id: "1", type: "scene" as const, name: "庙宇", description: "阴森古朴",
  voice_style: "", image_path: null, audio_path: null, source_project: "demo", updated_at: null,
};

describe("AssetCard", () => {
  it("shows name + description", () => {
    render(<AssetCard asset={asset} onEdit={() => {}} onDelete={() => {}} />);
    expect(screen.getByText("庙宇")).toBeInTheDocument();
    expect(screen.getByText("阴森古朴")).toBeInTheDocument();
  });

  it("invokes onEdit on edit button click", () => {
    const onEdit = vi.fn();
    render(<AssetCard asset={asset} onEdit={onEdit} onDelete={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /edit/ }));
    expect(onEdit).toHaveBeenCalledWith(asset);
  });

  it("invokes onDelete on delete button click", () => {
    const onDelete = vi.fn();
    render(<AssetCard asset={asset} onEdit={() => {}} onDelete={onDelete} />);
    fireEvent.click(screen.getByRole("button", { name: /delete/ }));
    expect(onDelete).toHaveBeenCalledWith(asset);
  });

  it("publishes a local asset", () => {
    const onShare = vi.fn();
    render(<AssetCard asset={asset} onEdit={() => {}} onDelete={() => {}} onShare={onShare} />);
    fireEvent.click(screen.getByRole("button", { name: "share_asset" }));
    expect(onShare).toHaveBeenCalledWith(asset);
  });

  it("allows the owner to publish a new shared version", () => {
    const onShare = vi.fn();
    const owned = {
      ...asset,
      external_origin: "user_shared" as const,
      company_publish_state: "update" as const,
    };
    render(<AssetCard asset={owned} onEdit={() => {}} onDelete={() => {}} onShare={onShare} />);
    fireEvent.click(screen.getByRole("button", { name: "share_asset_update" }));
    expect(onShare).toHaveBeenCalledWith(owned);
  });

  it("shows another user's shared asset as read-only without a publish button", () => {
    const otherUserAsset = {
      ...asset,
      external_origin: "user_shared" as const,
      external_owner_name: "Alice",
      company_publish_state: "read_only_other" as const,
    };
    render(
      <AssetCard asset={otherUserAsset} onEdit={() => {}} onDelete={() => {}} onShare={() => {}} />,
    );

    expect(screen.getByText("shared by Alice")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "share_asset_update" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "share_asset" })).not.toBeInTheDocument();
  });
});
