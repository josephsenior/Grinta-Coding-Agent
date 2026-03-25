import { cn } from "@/lib/utils";

/** Shared layout for cmdk CommandDialog (unstyled by default). */
export const CMDK_OVERLAY = cn(
  "fixed inset-0 z-50 bg-black/80",
  "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
);

export const CMDK_CONTENT = cn(
  "fixed left-1/2 top-[50%] z-50 grid w-[calc(100vw-1.5rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-0",
  "overflow-hidden rounded-xl border bg-popover p-0 text-popover-foreground shadow-lg outline-none",
  "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
  "data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
);

export const CMDK_ROOT = cn(
  "flex max-h-[min(70vh,560px)] w-full min-w-0 flex-col",
  "[&_[cmdk-input]]:h-11 [&_[cmdk-input]]:w-full [&_[cmdk-input]]:min-w-0 [&_[cmdk-input]]:border-0 [&_[cmdk-input]]:border-b [&_[cmdk-input]]:border-border [&_[cmdk-input]]:bg-transparent",
  "[&_[cmdk-input]]:px-3 [&_[cmdk-input]]:py-2 [&_[cmdk-input]]:text-sm [&_[cmdk-input]]:outline-none [&_[cmdk-input]]:ring-0 [&_[cmdk-input]]:placeholder:text-muted-foreground [&_[cmdk-input]]:focus-visible:ring-0",
  "[&_[cmdk-group-heading]]:select-none [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5",
  "[&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-muted-foreground",
  "[&_[cmdk-group-items]]:px-1 [&_[cmdk-group-items]]:pb-1.5",
  "[&_[cmdk-item]]:flex [&_[cmdk-item]]:cursor-pointer [&_[cmdk-item]]:select-none [&_[cmdk-item]]:items-center [&_[cmdk-item]]:gap-2",
  "[&_[cmdk-item]]:rounded-md [&_[cmdk-item]]:px-2 [&_[cmdk-item]]:py-2 [&_[cmdk-item]]:text-sm [&_[cmdk-item]]:outline-none",
  "[&_[cmdk-item][data-selected=true]]:bg-accent [&_[cmdk-item][data-selected=true]]:text-accent-foreground",
  "[&_[cmdk-item]_svg]:h-4 [&_[cmdk-item]_svg]:w-4 [&_[cmdk-item]_svg]:shrink-0",
  "[&_[cmdk-empty]]:px-3 [&_[cmdk-empty]]:py-6 [&_[cmdk-empty]]:text-center [&_[cmdk-empty]]:text-sm [&_[cmdk-empty]]:text-muted-foreground",
);
