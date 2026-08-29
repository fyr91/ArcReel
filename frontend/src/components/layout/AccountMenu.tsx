import { useEffect, useRef, useState } from "react";
import { ChevronDown, LogOut, UserRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAuthStore } from "@/stores/auth-store";

interface AccountMenuProps {
  className?: string;
  showIdentity?: boolean;
}

function accountInitial(value: string): string {
  return Array.from(value.trim())[0]?.toUpperCase() ?? "A";
}

/**
 * 当前登录账号菜单。
 *
 * Supabase 的 access/refresh token 只保存在本地后端，浏览器持有的是 ArcReel
 * 自己的短期会话令牌。因此这里清除浏览器会话后使用整页导航回登录页：既终止所有
 * 当前页面的在途请求与订阅，也让全部内存 store 在下一次登录前重新初始化，避免同一
 * 台电脑切换账号时短暂看到上一个账号的缓存数据。
 */
export function AccountMenu({ className = "", showIdentity = false }: AccountMenuProps) {
  const { t } = useTranslation("common");
  const token = useAuthStore((state) => state.token);
  const username = useAuthStore((state) => state.username);
  const displayName = useAuthStore((state) => state.displayName);
  const role = useAuthStore((state) => state.role);
  const logout = useAuthStore((state) => state.logout);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  // AUTH_ENABLED=false 时没有真实登录会话，也就没有可退出的账号。
  if (!token) return null;

  const identity = displayName || username || "ArcReel";
  const roleLabel = role === "admin" ? t("role_admin") : t("role_user");

  const handleLogout = () => {
    setOpen(false);
    logout();
    globalThis.location.replace("/login");
  };

  return (
    <div ref={rootRef} className={`relative ${className}`}>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("account_menu_for", { name: identity })}
        title={t("account_menu_for", { name: identity })}
        onClick={() => setOpen((current) => !current)}
        className="inline-flex h-[30px] items-center gap-1.5 rounded-md border border-hairline-soft bg-bg-grad-a/45 px-1.5 text-[11.5px] text-text-2 transition-colors hover:border-hairline hover:bg-bg-grad-a hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <span
          aria-hidden
          className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-accent-dim font-mono text-[10px] font-bold text-accent-2"
        >
          {accountInitial(identity)}
        </span>
        {showIdentity ? <span className="max-w-28 truncate">{identity}</span> : null}
        <ChevronDown
          aria-hidden
          className={`h-3 w-3 text-text-4 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open ? (
        <div
          role="menu"
          aria-label={t("account_menu")}
          className="absolute right-0 top-[calc(100%+8px)] z-50 w-56 overflow-hidden rounded-[10px] border border-hairline bg-bg-grad-a p-1.5 shadow-[0_18px_48px_-18px_oklch(0_0_0_/_0.75)]"
        >
          <div className="border-b border-hairline-soft px-2.5 py-2.5">
            <div className="flex items-center gap-2.5">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent-dim text-accent-2">
                <UserRound aria-hidden className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <div className="truncate text-[12.5px] font-semibold text-text">{identity}</div>
                <div className="mt-0.5 truncate text-[10.5px] text-text-4">
                  {username && username !== identity ? `${username} · ` : ""}{roleLabel}
                </div>
              </div>
            </div>
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={handleLogout}
            className="mt-1 flex w-full items-center gap-2 rounded-[7px] px-2.5 py-2 text-left text-[12px] text-text-2 transition-colors hover:bg-danger/10 hover:text-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger/50"
          >
            <LogOut aria-hidden className="h-3.5 w-3.5" />
            {t("logout")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
