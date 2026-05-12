import { useCallback, useState } from 'react';
import { getParsedApiError } from '../../../api/error';
import type { TaskInfo } from '../../../types/analysis';
import { useAnalysisStore } from '../../../stores/analysisStore';
import { useTaskStream } from '../../../hooks';

export interface UseActiveTasks {
  activeTasks: TaskInfo[];
}

/**
 * Wires the global SSE task stream into local list state and triggers the
 * caller-provided history refresh whenever a task completes.
 */
export function useActiveTasks(onTaskCompleted: () => void): UseActiveTasks {
  const { setError: setStoreError } = useAnalysisStore();
  const [activeTasks, setActiveTasks] = useState<TaskInfo[]>([]);

  const updateTask = useCallback((updatedTask: TaskInfo) => {
    setActiveTasks((prev) => {
      const index = prev.findIndex((t) => t.taskId === updatedTask.taskId);
      if (index >= 0) {
        const newTasks = [...prev];
        newTasks[index] = updatedTask;
        return newTasks;
      }
      return prev;
    });
  }, []);

  const removeTask = useCallback((taskId: string) => {
    setActiveTasks((prev) => prev.filter((t) => t.taskId !== taskId));
  }, []);

  useTaskStream({
    onTaskCreated: (task) => {
      setActiveTasks((prev) => {
        if (prev.some((t) => t.taskId === task.taskId)) return prev;
        return [...prev, task];
      });
    },
    onTaskStarted: updateTask,
    onTaskCompleted: (task) => {
      onTaskCompleted();
      setTimeout(() => removeTask(task.taskId), 2000);
    },
    onTaskFailed: (task) => {
      updateTask(task);
      setStoreError(getParsedApiError(task.error || '分析失败'));
      setTimeout(() => removeTask(task.taskId), 5000);
    },
    onError: () => {
      console.warn('SSE 连接断开，正在重连...');
    },
    enabled: true,
  });

  return { activeTasks };
}
