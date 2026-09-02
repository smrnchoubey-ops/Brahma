import { TaskDetailView } from "@/components/tasks/task-detail-view";

export default async function TaskDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  return <TaskDetailView taskId={id} />;
}