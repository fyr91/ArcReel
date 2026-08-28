import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import { useAssistantSession } from "@/hooks/useAssistantSession";
import { useCurrentEpisode } from "@/hooks/useCurrentEpisode";
import { useAppStore } from "@/stores/app-store";
import { useAssistantStore } from "@/stores/assistant-store";
import { useProjectsStore } from "@/stores/projects-store";
import { useTasksStore } from "@/stores/tasks-store";
import { useWorkflowStore } from "@/stores/workflow-store";
import { makePlan, makeTask } from "@/test/factories";
import { UI_LAYERS } from "@/utils/ui-layers";
import { AgentCopilot } from "./AgentCopilot";

vi.mock("@/hooks/useAssistantSession", () => ({
  useAssistantSession: vi.fn(),
}));

vi.mock("@/hooks/useCurrentEpisode", () => ({
  useCurrentEpisode: vi.fn(),
}));

vi.mock("./ContextBanner", () => ({
  ContextBanner: ({ episode }: { episode?: number }) => (
    <div data-testid="context-banner">{episode ?? "project"}</div>
  ),
}));

vi.mock("./SlashCommandMenu", () => ({
  SlashCommandMenu: vi.fn(() => null),
}));

vi.mock("./chat/ChatMessage", () => ({
  ChatMessage: ({ message }: { message: { type: string; content?: Array<{ text?: string }> } }) => {
    const text = message.content?.map((block) => block.text ?? "").join("") ?? "";
    return <div data-testid="chat-message">{message.type}:{text}</div>;
  },
}));

const mockedUseAssistantSession = vi.mocked(useAssistantSession);
const mockedUseCurrentEpisode = vi.mocked(useCurrentEpisode);

function makePendingQuestion() {
  return {
    question_id: "q-1",
    questions: [
      {
        header: "输出",
        question: "输出格式是什么？",
        multiSelect: false,
        options: [
          { label: "摘要", description: "简洁输出" },
          { label: "详细", description: "完整说明" },
        ],
      },
    ],
  };
}

describe("AgentCopilot", () => {
  // Mocks whose callers wrap them with voidPromise must return a Promise
  // so the .catch(...) chain in voidPromise resolves instead of crashing.
  const sendMessage = vi.fn().mockResolvedValue(undefined);
  const rewriteMessage = vi.fn().mockResolvedValue(true);
  const answerQuestion = vi.fn().mockResolvedValue(undefined);
  const interrupt = vi.fn().mockResolvedValue(undefined);
  const createNewSession = vi.fn();
  const switchSession = vi.fn().mockResolvedValue(undefined);
  const deleteSession = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    useAssistantStore.setState(useAssistantStore.getInitialState(), true);
    useProjectsStore.setState(useProjectsStore.getInitialState(), true);
    useAppStore.setState(useAppStore.getInitialState(), true);
    useTasksStore.setState(useTasksStore.getInitialState(), true);
    useWorkflowStore.getState().resetTarget();
    vi.clearAllMocks();
    mockedUseCurrentEpisode.mockReturnValue(undefined);
    vi.spyOn(API, "getWorkflowPlan").mockResolvedValue(makePlan({
      next_action: {
        type: "generate_asset_sheets",
        args: {},
        requested_ids: [],
        requires_confirmation: false,
        reason: "asset inventory completed",
      },
    }));

    useProjectsStore.getState().setCurrentProject("demo", null);
    mockedUseAssistantSession.mockReturnValue({
      sendMessage,
      rewriteMessage,
      answerQuestion,
      interrupt,
      createNewSession,
      switchSession,
      deleteSession,
    });
  });

  it("shows an immediate user bubble and transitions the animated send text until Agent activity", () => {
    useAssistantStore.setState({
      sending: true,
      awaitingAgentResponse: true,
      pendingUserTurn: {
        type: "user",
        content: [{ type: "text", text: "继续下一步" }],
        uuid: "pending-user:client-1",
      },
    });

    render(<AgentCopilot />);

    expect(screen.getByText("user:继续下一步")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("正在发送给 Agent");

    act(() => {
      useAssistantStore.setState({
        sending: false,
        pendingUserTurn: null,
        turns: [{
          type: "user",
          content: [{ type: "text", text: "继续下一步" }],
          uuid: "user-1",
        }],
      });
    });

    expect(screen.getAllByText("user:继续下一步")).toHaveLength(1);
    expect(screen.getByRole("status")).toHaveTextContent("Agent 已接收，正在处理");

    act(() => {
      useAssistantStore.getState().setDraftSnapshot({
        message_id: "assistant-1",
        content: [{ type: "thinking", thinking: "开始处理" }],
      }, 1);
    });

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders the pending-question wizard and disables normal sending", () => {
    useAssistantStore.setState({
      pendingQuestion: makePendingQuestion(),
      skills: [{ name: "plan", description: "Plan", scope: "project", path: "/tmp/plan" }],
    });

    render(<AgentCopilot />);

    expect(screen.getByText("需要你的选择")).toBeInTheDocument();
    expect(screen.getByLabelText("Agent 输入")).toBeDisabled();
    expect(screen.getByLabelText("发送消息")).toBeDisabled();
    expect(screen.getByPlaceholderText("请先回答上方问题")).toBeInTheDocument();
  });

  it("submits wizard answers through answerQuestion", () => {
    useAssistantStore.setState({
      pendingQuestion: makePendingQuestion(),
    });

    render(<AgentCopilot />);

    fireEvent.click(screen.getByLabelText("摘要"));
    fireEvent.click(screen.getByRole("button", { name: /完成并提交/ }));

    expect(answerQuestion).toHaveBeenCalledWith("q-1", {
      "输出格式是什么？": "摘要",
    });
  });

  it("keeps assistant root isolated and uses local popover layer for session history", () => {
    useAssistantStore.setState({
      sessions: [
        {
          id: "session-1",
          project_name: "demo",
          title: "当前会话",
          status: "idle",
          created_at: "2026-02-01T00:00:00Z",
          updated_at: "2026-02-01T00:00:00Z",
        },
      ],
      currentSessionId: "session-1",
    });

    const { container } = render(<AgentCopilot />);

    expect(container.firstElementChild).toHaveClass("isolate");

    fireEvent.click(screen.getByTitle("切换会话"));
    expect(document.querySelector(`.${UI_LAYERS.assistantLocalPopover}`)).toBeTruthy();
  });

  it("does not send when Enter is used to confirm an IME composition", () => {
    render(<AgentCopilot />);

    const textarea = screen.getByLabelText("Agent 输入");
    fireEvent.change(textarea, { target: { value: "你好" } });

    fireEvent.compositionStart(textarea);
    fireEvent.keyDown(textarea, {
      key: "Enter",
      code: "Enter",
      keyCode: 229,
      which: 229,
      isComposing: true,
    });

    expect(sendMessage).not.toHaveBeenCalled();

    fireEvent.compositionEnd(textarea);
    fireEvent.keyDown(textarea, {
      key: "Enter",
      code: "Enter",
      keyCode: 13,
      which: 13,
    });

    expect(sendMessage).toHaveBeenCalledWith("你好", undefined);
  });

  it("consumes a one-shot prefill dispatched via the assistant store's input field", async () => {
    render(<AgentCopilot />);

    act(() => {
      useAssistantStore.getState().setInput("为第 1 集生成剧本");
    });

    expect(screen.getByLabelText("Agent 输入")).toHaveValue("为第 1 集生成剧本");

    await waitFor(() => {
      expect(useAssistantStore.getState().input).toBe("");
    });
  });

  it("binds the Agent to the selected episode and preserves a separate unsent text draft per scope", () => {
    mockedUseCurrentEpisode.mockReturnValue(1);
    const { rerender } = render(<AgentCopilot />);
    const textarea = screen.getByLabelText("Agent 输入");
    fireEvent.change(textarea, { target: { value: "第一集草稿" } });

    mockedUseCurrentEpisode.mockReturnValue(2);
    rerender(<AgentCopilot />);
    expect(screen.getByLabelText("Agent 输入")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Agent 输入"), { target: { value: "第二集草稿" } });

    mockedUseCurrentEpisode.mockReturnValue(1);
    rerender(<AgentCopilot />);

    expect(screen.getByLabelText("Agent 输入")).toHaveValue("第一集草稿");
    expect(mockedUseAssistantSession).toHaveBeenLastCalledWith("demo", 1);
    expect(screen.getByTestId("context-banner")).toHaveTextContent("1");
  });

  it("sends a queued HyperFrames auto-edit through the same Agent session path", async () => {
    useAppStore.getState().requestHyperframesAutoEdit(
      "demo",
      "请使用 hyperframes-auto-edit Skill 对第 1 集执行完整自动剪辑。",
    );

    render(<AgentCopilot />);

    await waitFor(() => {
      expect(sendMessage).toHaveBeenCalledWith(
        "请使用 hyperframes-auto-edit Skill 对第 1 集执行完整自动剪辑。",
      );
      expect(useAppStore.getState().hyperframesAutoEditRequest).toBeNull();
    });
  });

  it("renders the project-scoped analysis handoff as an Agent message", () => {
    useAssistantStore.getState().showHandoffGuide("demo", 1);

    render(<AgentCopilot />);

    expect(
      screen.getByText(/剧本分析已完成，你可以继续项目制作了/),
    ).toBeInTheDocument();
    expect(screen.queryByText("开始对话")).not.toBeInTheDocument();
  });

  it("offers Start production after analysis handoff and sends the authoritative next action", async () => {
    useAssistantStore.getState().showHandoffGuide("demo", 1);

    render(<AgentCopilot />);

    expect(await screen.findByText("下一步：生成缺失的资产图")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /开始制作/ }));

    expect(sendMessage).toHaveBeenCalledWith(
      "开始制作。请查询当前项目的最新工作流计划，并执行下一步：生成缺失的资产图。",
    );
  });

  it("offers the next workflow step after a completed Agent round", async () => {
    vi.mocked(API.getWorkflowPlan).mockResolvedValue(makePlan({
      next_action: {
        type: "plan_episodes",
        args: {},
        requested_ids: [],
        requires_confirmation: false,
        reason: "asset sheets completed",
      },
    }));
    useAssistantStore.setState({
      currentSessionId: "session-1",
      sessionStatus: "completed",
    });

    render(<AgentCopilot />);

    expect(await screen.findByText("下一步：规划分集")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^下一步/ }));

    expect(sendMessage).toHaveBeenCalledWith(
      "请查询当前项目的最新工作流计划，并执行下一步：规划分集。",
    );
  });

  it("waits for a background subagent to settle before offering the next step", async () => {
    vi.mocked(API.getWorkflowPlan)
      .mockResolvedValueOnce(makePlan({
        next_action: {
          type: "analyze_assets",
          args: {},
          requested_ids: [],
          requires_confirmation: false,
          reason: "asset inventory running",
        },
      }))
      .mockResolvedValue(makePlan({
        next_action: {
          type: "generate_asset_sheets",
          args: {},
          requested_ids: [],
          requires_confirmation: false,
          reason: "asset inventory completed",
        },
      }));
    useAssistantStore.setState({
      currentSessionId: "session-1",
      sessionStatus: "completed",
      subagents: {
        "tu-1": {
          tool_use_id: "tu-1",
          task_id: "task-1",
          agent_type: "analyze-assets",
          description: "提取资产",
          started_at: "2026-08-28T00:00:00Z",
          status: "running",
          summary: "",
          usage: null,
          entries: [],
        },
      },
    });

    render(<AgentCopilot />);

    await waitFor(() => expect(API.getWorkflowPlan).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("button", { name: /^下一步/ })).not.toBeInTheDocument();

    act(() => {
      useAssistantStore.getState().setSubagentSnapshots([
        {
          tool_use_id: "tu-1",
          task_id: "task-1",
          agent_type: "analyze-assets",
          description: "提取资产",
          started_at: "2026-08-28T00:00:00Z",
          status: "completed",
          summary: "已提取资产",
          usage: null,
          entries: [],
        },
      ]);
    });

    await waitFor(() => expect(API.getWorkflowPlan).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("下一步：生成缺失的资产图")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^下一步/ })).toBeInTheDocument();
  });

  it("offers the authoritative next step while an unrelated project task is active", async () => {
    useAssistantStore.setState({
      currentSessionId: "session-1",
      sessionStatus: "completed",
    });
    useTasksStore.getState().setTasks([
      makeTask({ project_name: "demo", task_type: "voice_sample", status: "running" }),
    ]);

    render(<AgentCopilot />);

    await waitFor(() => expect(API.getWorkflowPlan).toHaveBeenCalled());
    expect(await screen.findByText("下一步：生成缺失的资产图")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^下一步/ })).toBeInTheDocument();
  });

  it("does not offer continuation when the workflow is waiting or finished", async () => {
    vi.mocked(API.getWorkflowPlan).mockResolvedValue(makePlan({
      next_action: {
        type: "wait_for_task",
        args: {},
        requested_ids: [],
        requires_confirmation: false,
        reason: "generation in progress",
      },
    }));
    useAssistantStore.setState({
      currentSessionId: "session-1",
      sessionStatus: "completed",
    });

    render(<AgentCopilot />);

    await waitFor(() => expect(API.getWorkflowPlan).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /^下一步/ })).not.toBeInTheDocument();
  });

  it("does not render a handoff guide that belongs to another project", () => {
    useAssistantStore.getState().showHandoffGuide("another-project", 1);

    render(<AgentCopilot />);

    expect(screen.queryByText(/剧本分析已完成/)).not.toBeInTheDocument();
  });

  it("clears the handoff guide when the conversation timeline resets", () => {
    useAssistantStore.getState().showHandoffGuide("demo", 1);

    useAssistantStore.getState().resetTimeline();

    expect(useAssistantStore.getState().handoffGuide).toBeNull();
  });

});
