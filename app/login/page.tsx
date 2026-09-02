"use client";

import { useRouter } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";

import { ErrorState } from "@/components/common/error-state";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");

    if (!email.includes("@") || password.length < 6) {
      setError("Enter a valid email and a password with at least 6 characters.");
      return;
    }

    setLoading(true);
    window.setTimeout(() => {
      router.push("/dashboard");
    }, 600);
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-8 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <ShieldCheck className="h-6 w-6" aria-hidden="true" />
          </div>
          <div>
            <p className="text-xl font-semibold">BRAHMA COS</p>
            <p className="text-sm text-muted-foreground">
              Founder command interface
            </p>
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Sign in</CardTitle>
            <CardDescription>
              Use any valid-looking credentials to enter the frontend prototype.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleSubmit}>
              {error ? <ErrorState message={error} /> : null}
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  autoComplete="email"
                  disabled={loading}
                  id="email"
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="founder@brahma.local"
                  type="email"
                  value={email}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  autoComplete="current-password"
                  disabled={loading}
                  id="password"
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Minimum 6 characters"
                  type="password"
                  value={password}
                />
              </div>
              <Button
                className="w-full"
                disabled={loading || !email || !password}
                type="submit"
              >
                {loading ? "Signing in" : "Login"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
