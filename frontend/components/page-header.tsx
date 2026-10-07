export function PageHeader({ title, description }: { title: string; description?: string }) {
  return (
    <header className="mb-8 space-y-1">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {description && <p className="text-muted-foreground">{description}</p>}
    </header>
  );
}
