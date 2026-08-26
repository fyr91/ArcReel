import { useEffect } from "react";
import { useProjectsStore } from "@/stores/projects-store";
import { useTasksStore } from "@/stores/tasks-store";
import { useWorkflowStore } from "@/stores/workflow-store";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";

/**
 * 一批生成任务会在同一轮轮询里连续跳状态；等待短窗口后再重求解，避免为同一批
 * 状态变化重复请求工作流计划。
 */
const PLAN_REFRESH_DEBOUNCE_MS = 250;

/**
 * 把项目事实与任务状态同步到共享 WorkflowPlan store。
 *
 * 工作流面板与 Agent 的「下一步」入口都消费同一份服务端计划，不能各自维护一套
 * content mode / action 映射。调用方用 enabled 明确当前路由由谁持有同步责任，避免
 * 同一目标被两个常驻组件重复刷新。
 */
export function useWorkflowPlanSync(
  projectName: string | null,
  episode: number | null,
  enabled = true,
  externalRevision = "",
): void {
  const refreshPlan = useWorkflowStore((state) => state.refreshPlan);
  const resetTarget = useWorkflowStore((state) => state.resetTarget);
  const snapshotRevision = useProjectsStore((state) =>
    projectName ? (state.projectSnapshotRevisions[projectName] ?? 0) : 0,
  );
  const narrationDelivery = useWorkflowStore((state) => state.narrationDelivery);
  const confirmedDurations = useWorkflowStore((state) => state.confirmedDurations);
  const taskFingerprint = useTasksStore((state) =>
    projectName
      ? state.tasks
          .filter((task) => task.project_name === projectName)
          .map((task) => `${task.task_id}:${task.status}`)
          .join("|")
      : "",
  );
  const settledTaskFingerprint = useDebouncedValue(taskFingerprint, PLAN_REFRESH_DEBOUNCE_MS);

  useEffect(() => {
    if (!enabled || !projectName) return;
    void refreshPlan(projectName, episode);
  }, [
    enabled,
    projectName,
    episode,
    snapshotRevision,
    settledTaskFingerprint,
    externalRevision,
    narrationDelivery,
    confirmedDurations,
    refreshPlan,
  ]);

  useEffect(() => {
    if (!enabled) return;
    return () => resetTarget();
  }, [enabled, resetTarget]);
}
