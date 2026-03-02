import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface CardSectionLabelProps {
  label: string;
  icon?: ReactNode;
  className?: string;
}

export function CardSectionLabel({ label, icon, className }: CardSectionLabelProps) {
  return (
    <div
      className={cn(
        "mb-1 flex items-center gap-1 text-[10px] font-normal tracking-normal text-muted-foreground/80",
        className,
      )}
    >
      {icon}
      <span>{label}</span>
    </div>
  );
}
