export interface Task {
  id: string;
  title: string;
  prompt: string;
  status: string;
  created_at: string;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getToken() {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("access_token");
    if (token) return token;
  }
  // Redirect to login if no token
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.href = "/login";
  }
  return null;
}

export async function getAllTasks(): Promise<Task[]> {
  const token = await getToken();
  const response = await fetch(`${API_BASE_URL}/tasks/`, {
    headers: { "Authorization": `Bearer ${token}` }
  });
  if (response.status === 401) {
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new Error("Unauthorized");
  }
  return await response.json();
}

export async function createTask(intent: string): Promise<Task> {
  const token = await getToken();
  const response = await fetch(`${API_BASE_URL}/tasks/`, {
    method: "POST",
    headers: { 
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}` 
    },
    body: JSON.stringify({ title: "New Task", prompt: intent }),
  });
  
  if (response.status === 401) {
    if (typeof window !== "undefined") {
        localStorage.removeItem("access_token");
        window.location.href = "/login";
    }
    throw new Error("Unauthorized");
  }
  if (!response.ok) throw new Error("Failed to create task");
  
  const data = await response.json();
  return {
    id: data.task_id,
    title: "New Task",
    prompt: intent,
    status: data.status,
    created_at: new Date().toISOString(),
  };
}

export async function getTaskStatus(taskId: string): Promise<any> {
  const token = await getToken();
  const response = await fetch(`${API_BASE_URL}/tasks/${taskId}`, {
    headers: { "Authorization": `Bearer ${token}` }
  });
  
  if (response.status === 401) {
    if (typeof window !== "undefined") {
        localStorage.removeItem("access_token");
        window.location.href = "/login";
    }
    throw new Error("Unauthorized");
  }
  if (!response.ok) throw new Error("Failed to fetch task status");
  
  return await response.json();
}

export async function getMetrics(): Promise<any> {
  const token = await getToken();
  const response = await fetch(`${API_BASE_URL}/api/metrics`, {
    headers: { "Authorization": `Bearer ${token}` }
  });
  if (response.status === 401) {
    if (typeof window !== "undefined") {
        localStorage.removeItem("access_token");
        window.location.href = "/login";
    }
    throw new Error("Unauthorized");
  }
  if (!response.ok) throw new Error("Failed to fetch metrics");
  return await response.json();
}

export async function getAgents(): Promise<any[]> {
  const token = await getToken();
  const response = await fetch(`${API_BASE_URL}/api/agents`, {
    headers: { "Authorization": `Bearer ${token}` }
  });
  if (response.status === 401) {
    if (typeof window !== "undefined") {
        localStorage.removeItem("access_token");
        window.location.href = "/login";
    }
    throw new Error("Unauthorized");
  }
  if (!response.ok) throw new Error("Failed to fetch agents");
  return await response.json();
}

export async function getAudit(): Promise<any[]> {
  const token = await getToken();
  const response = await fetch(`${API_BASE_URL}/api/audit`, {
    headers: { "Authorization": `Bearer ${token}` }
  });
  if (response.status === 401) {
    if (typeof window !== "undefined") {
        localStorage.removeItem("access_token");
        window.location.href = "/login";
    }
    throw new Error("Unauthorized");
  }
  if (!response.ok) throw new Error("Failed to fetch audit ledger");
  return await response.json();
}
