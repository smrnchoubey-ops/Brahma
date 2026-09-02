"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { BrainCircuit, Loader2 } from "lucide-react";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      const formData = new URLSearchParams();
      formData.append("username", username);
      formData.append("password", password);

      const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      
      const response = await fetch(`${API_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: formData.toString()
      });

      if (!response.ok) {
        throw new Error("Invalid credentials or server error");
      }

      const data = await response.json();
      // Store token
      if (typeof window !== "undefined") {
        localStorage.setItem("access_token", data.access_token);
      }
      
      // Redirect to command center
      router.push("/");
    } catch (err: any) {
      setError(err.message || "Authentication failed");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-[#09090b] text-slate-300 font-sans">
      <div className="w-full max-w-sm px-8 py-10 bg-[#0f172a]/50 border border-white/5 rounded-lg shadow-2xl backdrop-blur-md flex flex-col items-center">
        
        <div className="flex items-center justify-center mb-8">
          <BrainCircuit className="w-8 h-8 text-white mr-3" />
          <h1 className="text-xl font-bold tracking-widest uppercase text-white">Brahma COS</h1>
        </div>

        <form onSubmit={handleLogin} className="w-full space-y-5">
          <div className="space-y-1">
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Username</label>
            <input
              type="text"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-white/[0.02] border border-white/10 rounded p-2.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500/50 transition-colors"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Password</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-white/[0.02] border border-white/10 rounded p-2.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500/50 transition-colors"
            />
          </div>

          {error && (
            <div className="p-2.5 bg-red-500/10 border border-red-500/20 text-red-400 text-xs rounded">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={isLoading || !username || !password}
            className="w-full flex items-center justify-center bg-white text-black font-semibold rounded py-2.5 text-sm hover:bg-slate-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Authenticate"}
          </button>
        </form>
        
        <div className="mt-8 text-[10px] text-slate-600 uppercase tracking-widest">
          Secure Environment
        </div>
      </div>
    </div>
  );
}
