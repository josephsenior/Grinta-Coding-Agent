import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface CardSectionLabelProps {
  label: string;
  icon?: ReactNode;
  className?: string;
  /** Lighter, less visual weight (default). */
  variant?: "default" | "whisper";
}

export function CardSectionLabel({
  label,
  icon,
  className,
  variant = "default",
}: CardSectionLabelProps) {
  return (
    <div
      className={cn(
        "mb-1 flex items-center gap-1.5",
        variant === "whisper"
          ? "text-[10px] font-medium uppercase tracking-wider text-muted-foreground/45"
          : "text-[11px] font-medium tracking-wide text-muted-foreground/65",
        className,
      )}
    >
      {icon && <span className="text-muted-foreground/50 [&_svg]:h-3 [&_svg]:w-3">{icon}</span>}
      <span>{label}</span>
    </div>
  );
}
