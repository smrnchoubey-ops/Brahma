export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className="rounded-lg border bg-card p-5">
      <div className="flex items-center gap-3 text-sm text-muted-foreground">
        <span className="h-2 w-2 animate-pulse rounded-full bg-muted-foreground" />
        {label}
      </div>
    </div>
  );
}
