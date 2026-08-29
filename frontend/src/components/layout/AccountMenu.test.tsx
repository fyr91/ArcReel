import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AccountMenu } from "./AccountMenu";
import { useAuthStore } from "@/stores/auth-store";
import { getStoredUser, getToken } from "@/utils/auth";

describe("AccountMenu", () => {
  const replace = vi.fn();

  beforeEach(() => {
    useAuthStore.setState(useAuthStore.getInitialState(), true);
    replace.mockReset();
    vi.stubGlobal("location", { replace });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the current identity and completely clears the browser session on logout", () => {
    useAuthStore.getState().login(
      "arc-token",
      "alice",
      "admin",
      "user-1",
      "Alice",
      "arcreel_cloud",
    );

    render(<AccountMenu showIdentity />);

    fireEvent.click(screen.getByRole("button", { name: "Alice的账号菜单" }));
    expect(screen.getByRole("menu", { name: "账号菜单" })).toBeInTheDocument();
    expect(screen.getByText("alice · 管理员")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("menuitem", { name: "退出登录" }));

    expect(useAuthStore.getState()).toMatchObject({
      token: null,
      username: null,
      userId: null,
      role: null,
      isAuthenticated: false,
    });
    expect(getToken()).toBeNull();
    expect(getStoredUser()).toBeNull();
    expect(replace).toHaveBeenCalledWith("/login");
  });

  it("does not render when authentication is disabled and no token exists", () => {
    useAuthStore.setState({ isAuthenticated: true, isLoading: false, token: null });

    const { container } = render(<AccountMenu />);

    expect(container).toBeEmptyDOMElement();
  });
});
