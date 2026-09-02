"use client";

import { useEffect, useMemo, useState } from "react";
import { Plus, Search } from "lucide-react";
import api from "@/lib/api";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { PageHeader } from "@/components/common/page-header";
import { RiskBadge } from "@/components/common/risk-badge";
import { StatusBadge } from "@/components/common/status-badge";
import { TaskCard } from "@/components/tasks/task-card";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

import type { Task } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

export function TaskSubmitPanel({
  initialTasks,
}: {
  initialTasks: Task[];
}) {
  const [tasks, setTasks] = useState<Task[]>(initialTasks);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");

  const [search, setSearch] = useState("");

  const [loading, setLoading] = useState(false);

  const [error, setError] = useState("");

  const [success, setSuccess] = useState("");

  useEffect(() => {
    fetchTasks();
  }, []);

  async function fetchTasks() {
    try {
      const res = await api.get("/tasks/");
      setTasks(res.data.reverse());
    } catch (err) {
      console.error("Failed to load tasks", err);
    }
  }

  const filteredTasks = useMemo(() => {
    const normalized = search.trim().toLowerCase();

    if (!normalized) return tasks;

    return tasks.filter((task) =>
      [
        task.title,
        task.prompt,
        task.status,
        task.risk_level,
      ]
        .join(" ")
        .toLowerCase()
        .includes(normalized)
    );
  }, [search, tasks]);

  async function submitTask(
    event: React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    setError("");
    setSuccess("");

    if (!description.trim()) {
      setError("Please enter a task.");
      return;
    }

    setLoading(true);

    try {
      await api.post("/tasks/", {
        title: title.trim() || "Untitled Task",
        prompt: description,
      });

      setTitle("");
      setDescription("");

      setSuccess("Task submitted successfully!");

      await fetchTasks();
    } catch (err) {
      console.error(err);
      setError("Failed to submit task.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Task Console"
        description="Submit tasks directly to the BRAHMA backend."
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.4fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Submit Task</CardTitle>
            <CardDescription>
              Submit a task to KARMA.
            </CardDescription>
          </CardHeader>

          <CardContent>
            <form className="space-y-4" onSubmit={submitTask}>
              {error && <ErrorState message={error} />}

              {success && (
                <div className="rounded-lg border border-green-200 bg-green-50 p-4 text-sm text-green-700">
                  {success}
                </div>
              )}

              <div className="space-y-2">
                <Label htmlFor="title">
                  Optional Title
                </Label>

                <Input
                  id="title"
                  value={title}
                  disabled={loading}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Task title"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="description">
                  Task Description
                </Label>

                <Textarea
                  id="description"
                  value={description}
                  disabled={loading}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Describe your task..."
                />
              </div>

              <Button
                type="submit"
                disabled={loading || !description.trim()}
              >
                <Plus className="mr-2 h-4 w-4" />
                {loading ? "Submitting..." : "Submit Task"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <section className="space-y-4">
          <div className="flex flex-col gap-4 rounded-lg border bg-card p-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-base font-semibold">
                Recent Tasks
              </h2>

              <p className="mt-1 text-sm text-muted-foreground">
                Current task list.
              </p>
            </div>

            <div className="relative w-full sm:w-72">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />

              <Input
                className="pl-9"
                placeholder="Search..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </div>

          <div className="space-y-3">
            {filteredTasks.length ? (
              filteredTasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                />
              ))
            ) : (
              <EmptyState
                title="No Tasks"
                description="No matching tasks found."
                icon={Search}
              />
            )}
          </div>
        </section>
      </div>

      <div className="rounded-lg border bg-card p-5">
        <div className="grid gap-4 md:grid-cols-4">
          {tasks.slice(0, 4).map((task) => (
            <div key={task.id}>
              <p className="truncate text-sm font-medium">
                {task.title}
              </p>

              <div className="mt-2 flex flex-wrap gap-2">
                <StatusBadge status={task.status} />
                <RiskBadge level={task.risk_level} />
              </div>

              <p className="mt-2 text-xs text-muted-foreground">
                {formatDateTime(task.created_at)}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}